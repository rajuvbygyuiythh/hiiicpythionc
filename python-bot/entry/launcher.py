"""Visible diagnostics for the windowless EVA Bot Dashboard launcher."""
from __future__ import annotations

import datetime
import os
import sys
import traceback
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LOG_PATH = PROJECT_ROOT / "data" / "logs" / "gui_console.log"


def _show_native_error(message):
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "EVA Bot — Dashboard startup error", 0x10)
            return
        except Exception:
            pass
    print(message, file=sys.stderr, flush=True)


def _report_failure(exc, log_file, windowless, log_path):
    timestamp = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    summary = f"[{timestamp}] Dashboard startup failed: {type(exc).__name__}: {exc}"
    if log_file:
        try:
            log_file.write(summary + "\n")
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=log_file)
            log_file.flush()
        except Exception:
            pass

    reason = (
        "A required Python package or project file is missing. Run install.bat once "
        "from the project folder, then try again."
        if isinstance(exc, (ImportError, ModuleNotFoundError))
        else "The Dashboard encountered a startup error."
    )
    details = f"\n\nStartup details: {log_path}" if log_file else "\n\nThe startup log could not be written."
    message = f"EVA Bot could not open the Dashboard.\n\n{reason}{details}"
    if windowless:
        _show_native_error(message)
    else:
        print(message, file=sys.stderr, flush=True)
        traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)


def run(gui_main=None, log_path=DEFAULT_LOG_PATH):
    """Start the Dashboard and report import/startup failures visibly."""
    original_stdout = sys.stdout
    original_stderr = sys.stderr
    windowless = original_stdout is None or original_stderr is None
    log_file = None
    try:
        if log_path:
            log_path = Path(log_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = log_path.open("a", buffering=1, encoding="utf-8", errors="replace")
            log_file.write(
                f"\n[{datetime.datetime.now().astimezone().isoformat(timespec='seconds')}] "
                f"Starting EVA Bot with {sys.executable} (Python {sys.version.split()[0]})\n"
            )
            if windowless:
                sys.stdout = log_file
                sys.stderr = log_file
    except Exception:
        log_file = None

    try:
        if gui_main is None:
            from entry.main import main as gui_main
        gui_main()
        return 0
    except SystemExit as exc:
        code = exc.code
        if code in (None, 0):
            return 0
        _report_failure(exc, log_file, windowless, log_path)
        return code if isinstance(code, int) else 1
    except Exception as exc:
        _report_failure(exc, log_file, windowless, log_path)
        return 1
    finally:
        if log_file:
            try:
                log_file.flush()
            except Exception:
                pass
            if windowless:
                if sys.stdout is log_file:
                    sys.stdout = original_stdout
                if sys.stderr is log_file:
                    sys.stderr = original_stderr
            try:
                log_file.close()
            except Exception:
                pass


def main():
    raise SystemExit(run())


if __name__ == "__main__":
    main()
