"""Offline tests for the Dashboard's standalone CDP browser launcher."""
import ast
import contextlib
import io
import json
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import capture
import browser.cdp_capture_launcher as cdp_capture_launcher
from browser.cdp_capture_launcher import (
    find_browser_executable,
    build_browser_command,
    build_capture_command,
    cdp_endpoint_ready,
    console_python_executable,
    launch_capture_process,
    make_temporary_profile_dir,
    remove_temporary_profile,
    resolve_browser_executable,
    reserve_loopback_port,
    stop_capture_browser,
    stop_capture_process,
)


class _Response:
    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _limit):
        return json.dumps(self.value).encode("utf-8")


class _Opener:
    def __init__(self, response):
        self.response = response

    def open(self, _request, timeout=None):
        return self.response


class CDPCaptureLauncherTests(unittest.TestCase):
    def test_browser_command_is_loopback_only_and_uses_dedicated_profile(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            browser = Path(temp_dir) / "chrome.exe"
            browser.touch()
            profile = Path(temp_dir) / "isolated-profile"
            command = build_browser_command(browser, profile, 9333)

        self.assertEqual(command[0], str(browser.resolve()))
        self.assertIn("--remote-debugging-address=127.0.0.1", command)
        self.assertIn("--remote-debugging-port=9333", command)
        self.assertIn("--remote-allow-origins=http://localhost", command)
        self.assertIn(f"--user-data-dir={profile.resolve()}", command)
        self.assertEqual(command[-1], "about:blank")

    def test_browser_command_rejects_invalid_ports(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            browser = Path(temp_dir) / "chrome"
            browser.touch()
            with self.assertRaises(ValueError):
                build_browser_command(browser, temp_dir, 70000)

    def test_resolve_browser_executable_accepts_a_selected_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            browser = Path(temp_dir) / "chrome.exe"
            browser.touch()
            self.assertEqual(resolve_browser_executable(str(browser)), str(browser.resolve()))

    def test_auto_detection_uses_configured_browser_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            browser = Path(temp_dir) / "chrome.exe"
            browser.touch()
            with patch.dict("os.environ", {"EVA_CDP_BROWSER": str(browser)}):
                self.assertEqual(find_browser_executable(), str(browser.resolve()))

    def test_dashboard_launcher_imports_resolve_to_existing_helpers(self):
        project_root = Path(__file__).resolve().parents[1]
        tree = ast.parse((project_root / "entry" / "main.py").read_text(encoding="utf-8"))
        imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.module == "browser.cdp_capture_launcher"
            for alias in node.names
        }
        self.assertTrue(imported_names)
        missing = sorted(name for name in imported_names if not hasattr(cdp_capture_launcher, name))
        self.assertEqual(missing, [])

    def test_reserve_loopback_port_returns_a_valid_port(self):
        port = reserve_loopback_port()
        self.assertGreaterEqual(port, 1)
        self.assertLessEqual(port, 65535)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", port))

    def test_endpoint_check_requires_the_expected_loopback_websocket_url(self):
        good_response = _Response({"webSocketDebuggerUrl": "ws://127.0.0.1:9333/devtools/browser/id"})
        with patch("browser.cdp_capture_launcher.build_opener", return_value=_Opener(good_response)):
            self.assertTrue(cdp_endpoint_ready(9333))

        bad_response = _Response({"webSocketDebuggerUrl": "ws://192.0.2.10:9333/devtools/browser/id"})
        with patch("browser.cdp_capture_launcher.build_opener", return_value=_Opener(bad_response)):
            self.assertFalse(cdp_endpoint_ready(9333))

        wrong_port = _Response({"webSocketDebuggerUrl": "ws://localhost:9222/devtools/browser/id"})
        with patch("browser.cdp_capture_launcher.build_opener", return_value=_Opener(wrong_port)):
            self.assertFalse(cdp_endpoint_ready(9333))

    def test_capture_command_uses_local_endpoint_and_dashboard_stop_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "capture.py").write_text("# test script\n", encoding="utf-8")
            stop_file = root / "profile" / "capture.stop"
            command = build_capture_command("python", root, 9333, stop_file)

        self.assertEqual(command[0], "python")
        self.assertEqual(command[1], str((root / "capture.py").resolve()))
        self.assertIn("http://127.0.0.1:9333", command)
        self.assertIn("http://localhost", command)
        self.assertIn("--stop-file", command)
        self.assertEqual(command[-1], str(stop_file.resolve()))

    def test_capture_stop_file_exits_cleanly_and_closes_writer(self):
        class FakeCDPClient:
            def __init__(self, *_args, **_kwargs):
                self._reader_error = None
                self.closed = False

            def close(self):
                self.closed = True

        class FakeCapture:
            def __init__(self, *_args, **_kwargs):
                self._started_at = time.monotonic()
                self._session_info = {}

            def initialize(self):
                return None

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "output"
            stop_file = root / "profile" / "capture.stop"
            stop_file.parent.mkdir()
            stop_file.touch()
            args = [
                "--browser-url", "http://127.0.0.1:9333",
                "--duration", "0",
                "--output-dir", str(output_dir),
                "--stop-file", str(stop_file),
            ]
            with patch("capture._local_browser_ws_url", return_value="ws://127.0.0.1:9333/devtools/browser/id"), \
                    patch("capture.CDPClient", FakeCDPClient), \
                    patch("capture.CDPMetadataCapture", FakeCapture), \
                    contextlib.redirect_stdout(io.StringIO()):
                result = capture.main(args)

            traces = list(output_dir.glob("cdp-*/capture.jsonl"))
            self.assertEqual(result, 0)
            self.assertEqual(len(traces), 1)
            records = [json.loads(line) for line in traces[0].read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records[0]["kind"], "capture_started")
            self.assertEqual(records[-1]["kind"], "capture_stopped")

    def test_pythonw_resolves_to_sibling_python_when_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pythonw = Path(temp_dir) / "pythonw.exe"
            python = Path(temp_dir) / "python.exe"
            pythonw.touch()
            python.touch()
            self.assertEqual(console_python_executable(pythonw), str(python))

    def test_temporary_profile_cleanup_is_limited_to_created_profiles(self):
        profile = make_temporary_profile_dir()
        self.assertTrue(Path(profile).is_dir())
        self.assertTrue(remove_temporary_profile(profile))
        self.assertFalse(Path(profile).exists())

        with tempfile.TemporaryDirectory() as unrelated:
            self.assertFalse(remove_temporary_profile(unrelated))

    def test_browser_tree_stop_confirms_its_owned_process_exited(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            process = launch_capture_process(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                temp_dir,
            )
            self.assertTrue(stop_capture_browser(process, timeout=1.0))
            self.assertIsNotNone(process.poll())

    def test_stop_process_uses_graceful_stop_file_then_terminates_if_needed(self):
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                stop_file = Path(temp_dir) / "stop"
                stop_capture_process(process, stop_file, timeout=0.05)
                self.assertTrue(stop_file.exists())
            self.assertIsNotNone(process.poll())
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=2)


if __name__ == "__main__":
    unittest.main()
