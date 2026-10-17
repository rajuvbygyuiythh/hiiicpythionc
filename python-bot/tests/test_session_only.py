"""Offline checks for login-save and manual-debug modes; no browser or Qt needed."""

from __future__ import annotations

import sys
import threading
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class _Signal:
    def __init__(self, *args, **kwargs):
        self.emitted = []

    def connect(self, *args, **kwargs):
        return None

    def emit(self, *args):
        self.emitted.append(args)


def _stub_platform_modules():
    if "winsound" not in sys.modules:
        sys.modules["winsound"] = types.ModuleType("winsound")
    if "PyQt6" not in sys.modules:
        package = types.ModuleType("PyQt6")
        core = types.ModuleType("PyQt6.QtCore")
        core.QObject = object
        core.QThread = object
        core.pyqtSignal = lambda *args, **kwargs: _Signal()
        package.QtCore = core
        sys.modules["PyQt6"] = package
        sys.modules["PyQt6.QtCore"] = core


_stub_platform_modules()

from browser.browser_automation import ChitchatAutomation
from entry.thread_manager import ThreadManager


class SessionOnlyTests(unittest.TestCase):
    def make_automation(self, session_only=True, saved=True):
        automation = object.__new__(ChitchatAutomation)
        automation.session_only = session_only
        automation.manual_debug = False
        automation._stop_event = threading.Event()
        automation._session_started_in_attempt = False
        automation._ban_detected = False
        automation._save_successful_account_session = Mock(return_value=saved)
        automation._emit_session = Mock()
        automation.is_running = False
        automation.continuous_chat_loop = Mock()
        automation.logs = []
        automation.statuses = []
        automation.log = automation.logs.append
        automation.set_status = automation.statuses.append
        return automation

    def test_login_save_only_returns_after_authentication_without_starting_chat(self):
        automation = self.make_automation(session_only=True)
        automation.account_mode = "login"
        automation.hide_after_login = False
        automation.login_with_account = Mock(return_value=True)

        self.assertTrue(automation.start_chitchat_session(object()))
        automation.login_with_account.assert_called_once()
        automation.continuous_chat_loop.assert_not_called()
        self.assertTrue(any("will not start a chat" in line for line in automation.logs))

    def test_save_only_saves_and_never_enters_chat_loop(self):
        automation = self.make_automation(session_only=True, saved=True)
        page = object()

        self.assertTrue(automation._run_authenticated_session(page))
        automation._save_successful_account_session.assert_called_once_with(page)
        automation.continuous_chat_loop.assert_not_called()
        self.assertTrue(any("Closing the browser" in line for line in automation.logs))
        self.assertEqual(automation.statuses[-1], "Session saved; closing browser...")

    def test_save_failure_still_skips_chat(self):
        automation = self.make_automation(session_only=True, saved=False)

        self.assertTrue(automation._run_authenticated_session(object()))
        automation.continuous_chat_loop.assert_not_called()
        self.assertTrue(any("Save failed" in line for line in automation.logs))

    def test_normal_mode_keeps_existing_chat_and_final_checkpoint(self):
        automation = self.make_automation(session_only=False)
        page = object()

        self.assertTrue(automation._run_authenticated_session(page))
        automation.continuous_chat_loop.assert_called_once_with(page)
        self.assertEqual(automation._save_successful_account_session.call_count, 2)

    def test_manual_debug_rejects_create_and_save_only_combinations(self):
        with self.assertRaises(ValueError):
            ChitchatAutomation(account_mode="create", manual_debug=True)
        with self.assertRaises(ValueError):
            ChitchatAutomation(account_mode="login", session_only=True, manual_debug=True)
        with self.assertRaises(ValueError):
            ThreadManager(account_mode="create", manual_debug=True)

    def test_manual_debug_login_stops_before_chat_startup(self):
        automation = self.make_automation(session_only=False)
        automation.manual_debug = True
        automation.account_mode = "login"
        automation.hide_after_login = False
        automation.login_with_account = Mock(return_value=True)

        self.assertTrue(automation.start_chitchat_session(object()))
        automation.login_with_account.assert_called_once()
        automation.continuous_chat_loop.assert_not_called()
        self.assertTrue(any("visible browser is ready for manual" in line for line in automation.logs))

    def test_manual_debug_keeps_browser_open_until_stop_without_bot_chat(self):
        automation = self.make_automation(session_only=False)
        automation.manual_debug = True
        automation.is_running = True
        page = SimpleNamespace(is_closed=Mock(return_value=False))

        class StopAfterTwoWaits:
            def __init__(self):
                self.timeouts = []

            def wait(self, timeout):
                self.timeouts.append(timeout)
                return len(self.timeouts) >= 2

        stop_event = StopAfterTwoWaits()
        automation._stop_event = stop_event

        self.assertTrue(automation._run_authenticated_session(page))
        self.assertEqual(stop_event.timeouts, [0.25, 0.25])
        page.is_closed.assert_called_once()
        automation._save_successful_account_session.assert_not_called()
        automation.continuous_chat_loop.assert_not_called()
        self.assertEqual(automation.statuses[-1], "Manual browser open — chat yourself; STOP to close")

    def test_thread_manager_manual_debug_forces_visible_browser_and_one_worker(self):
        manager = ThreadManager(
            accounts=[{"email": "one@example.test", "password": "unused"}],
            manual_debug=True,
            headless=True,
            hide_after_login=True,
        )
        manager._runtime_cfg = {
            "mode": "safe",
            "multi_browser_min": 2,
            "go_engine_enabled": False,
            "go_engine_min_browsers": 2,
            "context_pool_enabled": False,
        }
        manager.account_mode = "login"
        manager._stagger_interval = 0.0
        manager.thread_log = _Signal()
        manager._wire_governor = Mock()
        manager._maybe_start_engine = Mock()
        manager._start_single_thread = Mock()

        manager.start_threads(4)

        self.assertEqual(manager.thread_count, 1)
        self.assertFalse(manager.headless)
        self.assertFalse(manager.hide_after_login)
        manager._start_single_thread.assert_called_once_with(1)

    def test_thread_manager_does_not_restart_after_manual_debug_worker_finishes(self):
        manager = object.__new__(ThreadManager)
        worker = SimpleNamespace(automation=SimpleNamespace(_context_pool_slot=None))
        manager.session_only = False
        manager.manual_debug = True
        manager.is_running = True
        manager.accounts_exhausted = False
        manager.workers = {1: worker}
        manager.account_lock = threading.Lock()
        manager.thread_accounts = {1: {"email": "one@example.test"}}
        manager.failed_accounts = set()
        manager._account_key = lambda account: account["email"]
        manager._unregister_worker_with_engine = lambda thread_id: None
        manager.thread_log = _Signal()
        manager.thread_finished = _Signal()
        manager.all_threads_finished = _Signal()

        manager._on_thread_finished(1)

        self.assertFalse(manager.is_running)
        self.assertEqual(manager.workers, {})
        self.assertEqual(manager.thread_finished.emitted, [(1,)])
        self.assertEqual(manager.all_threads_finished.emitted, [()])
        self.assertFalse(manager.failed_accounts)

    def test_thread_manager_does_not_restart_after_save_only_worker_finishes(self):
        manager = object.__new__(ThreadManager)
        worker = SimpleNamespace(automation=SimpleNamespace(_context_pool_slot=None))
        manager.session_only = True
        manager.is_running = True
        manager.accounts_exhausted = False
        manager.workers = {1: worker}
        manager.account_lock = threading.Lock()
        manager.thread_accounts = {1: {"email": "one@example.test"}}
        manager.failed_accounts = set()
        manager._account_key = lambda account: account["email"]
        manager._unregister_worker_with_engine = lambda thread_id: None
        manager.thread_log = _Signal()
        manager.thread_finished = _Signal()
        manager.all_threads_finished = _Signal()

        manager._on_thread_finished(1)

        self.assertFalse(manager.is_running)
        self.assertEqual(manager.workers, {})
        self.assertEqual(manager.thread_finished.emitted, [(1,)])
        self.assertEqual(manager.all_threads_finished.emitted, [()])
        self.assertFalse(manager.failed_accounts)


if __name__ == "__main__":
    unittest.main()
