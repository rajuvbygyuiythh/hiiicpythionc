"""Offline startup-error reporting checks for the windowless GUI launcher."""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from entry.launcher import run


class LauncherTests(unittest.TestCase):
    def test_successful_gui_entry_returns_zero(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = run(lambda: None, Path(temp_dir) / "gui.log")
        self.assertEqual(result, 0)

    def test_import_failure_is_logged_and_gives_install_guidance(self):
        def missing_package():
            raise ModuleNotFoundError("No module named 'PyQt6'")

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "data" / "logs" / "gui.log"
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                result = run(missing_package, log_path)

            log = log_path.read_text(encoding="utf-8")

        self.assertEqual(result, 1)
        self.assertIn("install.bat", errors.getvalue())
        self.assertIn("ModuleNotFoundError", log)
        self.assertIn("PyQt6", log)

    def test_windowless_startup_failure_uses_native_error_notice(self):
        def fail_to_start():
            raise RuntimeError("startup failed")

        with tempfile.TemporaryDirectory() as temp_dir:
            log_path = Path(temp_dir) / "gui.log"
            with patch("entry.launcher.sys.stdout", None), \
                    patch("entry.launcher.sys.stderr", None), \
                    patch("entry.launcher._show_native_error") as show_error:
                result = run(fail_to_start, log_path)

        self.assertEqual(result, 1)
        show_error.assert_called_once()
        self.assertIn("gui.log", show_error.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
