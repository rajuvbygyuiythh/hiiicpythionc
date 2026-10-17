"""Helpers for Dashboard-launched, loopback-only manual CDP capture."""
from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_PROFILE_PREFIX = "eva-cdp-profile-"


def resolve_browser_executable(value=""):
    """Resolve a selected or auto-detected Chrome/Chromium/Edge executable."""
    selected = os.path.expandvars(os.path.expanduser(str(value or "").strip().strip('"')))
    if selected:
        candidate = Path(selected)
        if candidate.is_file():
            return str(candidate.resolve())
        found = shutil.which(selected)
        if found:
            return str(Path(found).resolve())
        return ""

    configured = os.environ.get("EVA_CDP_BROWSER", "").strip()
    if configured:
        resolved = resolve_browser_executable(configured)
        if resolved:
            return resolved

    for name in ("chrome.exe", "chrome", "chromium.exe", "chromium", "chromium-browser", "msedge.exe", "msedge"):
        found = shutil.which(name)
        if found:
            return str(Path(found).resolve())

    roots = [
        os.environ.get("PROGRAMFILES", ""),
        os.environ.get("PROGRAMFILES(X86)", ""),
        os.environ.get("LOCALAPPDATA", ""),
    ]
    relative_paths = (
        Path("Google/Chrome/Application/chrome.exe"),
        Path("Chromium/Application/chrome.exe"),
        Path("Microsoft/Edge/Application/msedge.exe"),
    )
    for root in roots:
        if not root:
            continue
        for relative in relative_paths:
            candidate = Path(root) / relative
            if candidate.is_file():
                return str(candidate.resolve())

    for candidate in (
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
    ):
        if candidate.is_file():
            return str(candidate.resolve())
    return ""


def find_browser_executable():
    """Return the first installed browser found by the auto-detection rules."""
    return resolve_browser_executable()


def reserve_loopback_port():
    """Return an unused local TCP port for this short-lived browser session."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def make_temporary_profile_dir():
    """Create an isolated browser profile outside the project tree."""
    return tempfile.mkdtemp(prefix=_PROFILE_PREFIX)


def build_browser_command(executable, profile_dir, port):
    """Build safe Chromium flags: dedicated profile and loopback CDP only."""
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise ValueError("CDP port must be an integer") from None
    if not 1 <= port <= 65535:
        raise ValueError("CDP port must be between 1 and 65535")
    resolved = resolve_browser_executable(executable)
    if not resolved:
        raise FileNotFoundError("Select an installed Chrome, Chromium, or Edge executable")
    profile = str(Path(profile_dir).resolve())
    return [
        resolved,
        "--remote-debugging-address=127.0.0.1",
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=http://localhost",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "about:blank",
    ]


def launch_capture_browser(executable, profile_dir, port):
    """Launch an isolated visible browser in its own process group."""
    command = build_browser_command(executable, profile_dir, port)
    options = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    else:
        options["start_new_session"] = True
    return subprocess.Popen(command, **options)


def launch_capture_process(command, project_root):
    """Run capture.py without opening a second console window on Windows."""
    options = {
        "cwd": str(Path(project_root).resolve()),
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    else:
        options["start_new_session"] = True
    return subprocess.Popen(list(command), **options)


def stop_capture_process(process, stop_file=None, timeout=2.0):
    """Request a graceful capture stop, then terminate only that Python process."""
    if process is None or process.poll() is not None:
        return
    if stop_file:
        try:
            Path(stop_file).touch(exist_ok=True)
        except Exception:
            pass
    try:
        process.wait(timeout=max(0.2, float(timeout)))
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        process.terminate()
        process.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=1.0)
        except Exception:
            pass
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def stop_capture_browser(process, timeout=3.0):
    """Stop only the dedicated browser process tree created by this module."""
    if process is None:
        return True
    if process.poll() is not None:
        try:
            process.wait(timeout=0)
        except Exception:
            pass
        return True

    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=max(1.0, float(timeout)),
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            try:
                process.terminate()
            except Exception:
                pass
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        except Exception:
            try:
                process.terminate()
            except Exception:
                pass

    try:
        process.wait(timeout=max(0.2, float(timeout)))
    except subprocess.TimeoutExpired:
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except Exception:
                pass
        try:
            process.kill()
            process.wait(timeout=1.0)
        except Exception:
            pass
    except Exception:
        pass
    return process.poll() is not None


def remove_temporary_profile(profile_dir):
    """Delete only profiles created by ``make_temporary_profile_dir``."""
    if not profile_dir:
        return False
    try:
        path = Path(profile_dir).resolve()
        temp_root = Path(tempfile.gettempdir()).resolve()
        if path.parent != temp_root or not path.name.startswith(_PROFILE_PREFIX):
            return False
        shutil.rmtree(path, ignore_errors=True)
        return not path.exists()
    except Exception:
        return False


def cdp_endpoint_ready(port, timeout=0.35):
    """Check that the expected local Chromium CDP endpoint is ready."""
    try:
        port = int(port)
        request = Request(
            f"http://127.0.0.1:{port}/json/version",
            headers={"Accept": "application/json"},
        )
        opener = build_opener(ProxyHandler({}))
        with opener.open(request, timeout=max(0.1, float(timeout))) as response:
            metadata = json.loads(response.read(64_000).decode("utf-8"))
        websocket_url = urlsplit(str(metadata.get("webSocketDebuggerUrl") or ""))
        websocket_port = websocket_url.port or 80
        return (
            websocket_url.scheme == "ws"
            and (websocket_url.hostname or "").lower() in _LOCAL_HOSTS
            and websocket_port == port
        )
    except Exception:
        return False


def console_python_executable(current=None):
    """Prefer python.exe over pythonw.exe so the capture process can run reliably."""
    current = str(current or sys.executable)
    if Path(current).name.lower() in {"pythonw.exe", "pythonw"}:
        console = Path(current).with_name("python.exe")
        if console.is_file():
            return str(console)
    return current


def build_capture_command(python_executable, project_root, port, stop_file):
    """Build the metadata-only capture command used by Dashboard."""
    root = Path(project_root).resolve()
    script = root / "capture.py"
    if not script.is_file():
        raise FileNotFoundError(f"CDP capture script not found: {script}")
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise ValueError("CDP port must be an integer") from None
    if not 1 <= port <= 65535:
        raise ValueError("CDP port must be between 1 and 65535")
    return [
        str(python_executable),
        str(script),
        "--browser-url",
        f"http://127.0.0.1:{port}",
        "--origin",
        "http://localhost",
        "--duration",
        "0",
        "--output-dir",
        str(root / "capture"),
        "--stop-file",
        str(Path(stop_file).resolve()),
    ]
