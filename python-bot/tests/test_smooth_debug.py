"""Offline tests for runtime diagnostics and polling safeguards."""

from __future__ import annotations

import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import debug
from core.config_loader import normalize_performance


@contextmanager
def debug_env(value):
    had_value = "EVA_DEBUG" in os.environ
    previous = os.environ.get("EVA_DEBUG")
    if value is None:
        os.environ.pop("EVA_DEBUG", None)
    else:
        os.environ["EVA_DEBUG"] = value
    try:
        yield
    finally:
        if had_value:
            os.environ["EVA_DEBUG"] = previous
        else:
            os.environ.pop("EVA_DEBUG", None)


class DebugHelperTests(unittest.TestCase):
    def test_debug_flag_is_opt_in_and_case_insensitive(self):
        with debug_env(None):
            self.assertFalse(debug.is_debug())
        with debug_env("false"):
            self.assertFalse(debug.is_debug())
        for value in ("1", "true", "TRUE", "yes", "on", " 1 "):
            with self.subTest(value=value), debug_env(value):
                self.assertTrue(debug.is_debug())

    def test_debug_message_is_gated_and_redacted(self):
        lines = []
        with debug_env(None):
            debug.dbg(lines.append, "password=clear-text")
        self.assertEqual(lines, [])

        with debug_env("1"):
            debug.dbg(lines.append, "request failed: password=clear-text")
        self.assertEqual(lines, ["request failed: password=[REDACTED]"])

    def test_redactor_masks_credentials_but_preserves_regular_text(self):
        text = (
            "Authorization: Bearer abc.def; cookie=sid=xyz; "
            "url=https://alice:secret@example.test; note=ordinary"
        )
        safe = debug.redact_secrets(text)
        self.assertNotIn("abc.def", safe)
        self.assertNotIn("sid=xyz", safe)
        self.assertNotIn("alice:secret", safe)
        self.assertIn("note=ordinary", safe)

        self.assertEqual(
            debug.redact_secrets("Cookie: sid=abc; csrf=def"),
            "Cookie: [REDACTED]",
        )

    def test_redaction_is_idempotent_and_logger_failures_are_safe(self):
        value = "Cookie: sid=abc; password=clear"
        safe = debug.redact_secrets(value)
        self.assertEqual(debug.redact_secrets(safe), safe)

        def broken_logger(_message):
            raise RuntimeError("logger unavailable")

        with debug_env("1"):
            debug.dbg(broken_logger, "token=hidden")
            with debug.timed(broken_logger, "phase"):
                pass
            debug.exc(broken_logger, "phase failed", RuntimeError("token=hidden"))

    def test_timing_is_debug_only_and_respects_threshold(self):
        lines = []
        with debug_env(None):
            with debug.timed(lines.append, "extract"):
                pass
        self.assertEqual(lines, [])

        with debug_env("1"):
            with debug.timed(lines.append, "extract"):
                pass
            with debug.timed(lines.append, "filtered", threshold_ms=1_000_000):
                pass
        self.assertEqual(len(lines), 1)
        self.assertRegex(lines[0], r"^\[T\] extract: \d+\.\d+ms$")

    def test_timing_does_not_swallow_the_wrapped_exception(self):
        lines = []
        with debug_env("1"), self.assertRaisesRegex(ValueError, "expected"):
            with debug.timed(lines.append, "failing phase"):
                raise ValueError("expected")
        self.assertEqual(len(lines), 1)
        self.assertTrue(lines[0].startswith("[T] failing phase: "))

    def test_exception_traceback_uses_the_passed_exception_and_redacts(self):
        try:
            raise RuntimeError("request failed: token=do-not-log")
        except RuntimeError as error:
            saved_error = error

        lines = []
        with debug_env(None):
            debug.exc(lines.append, "[Chat] send", saved_error)
        self.assertEqual(len(lines), 1)
        self.assertIn("RuntimeError", lines[0])
        self.assertNotIn("do-not-log", lines[0])

        lines = []
        with debug_env("1"):
            debug.exc(lines.append, "[Chat] send", saved_error)
        joined = "\n".join(lines)
        self.assertIn("RuntimeError", joined)
        self.assertIn("test_exception_traceback_uses_the_passed_exception", joined)
        self.assertNotIn("do-not-log", joined)

    def test_non_raised_exception_reports_missing_traceback(self):
        lines = []
        with debug_env("1"):
            debug.exc(lines.append, "[Chat] send", RuntimeError("not raised"))
        self.assertTrue(any("traceback unavailable" in line for line in lines))

    def test_adaptive_interval_and_invalid_inputs(self):
        choose = debug.adaptive_interval
        self.assertEqual(choose(0.3, 30, 0.8, 100, 110), 0.3)
        self.assertEqual(choose(0.3, 30, 0.8, 100, 130), 0.8)
        self.assertEqual(choose(0.3, 30, 0.8, 100, 131), 0.8)
        self.assertEqual(choose("bad", 30, 0.8, 0, 1), 0.5)
        self.assertEqual(choose(0.3, "bad", 0.8, 0, 100), 0.3)
        self.assertEqual(choose(0.3, 0, float("nan"), 0, 1), 0.3)
        self.assertEqual(choose(0.3, 0, 0.8, float("nan"), 100), 0.3)
        self.assertEqual(choose(0.3, 0, 0.8, 0, float("inf")), 0.3)
        self.assertEqual(choose(-1, 30, 0.8, 0, 1), 0.5)

    def test_performance_config_has_safe_idle_defaults_and_overrides(self):
        defaults = normalize_performance({})
        self.assertEqual(defaults["idle_poll_after_seconds"], 30.0)
        self.assertEqual(defaults["idle_poll_interval_seconds"], 1.5)

        overrides = normalize_performance({
            "idle_poll_after_seconds": 12,
            "idle_poll_interval_seconds": 1.25,
        })
        self.assertEqual(overrides["idle_poll_after_seconds"], 12.0)
        self.assertEqual(overrides["idle_poll_interval_seconds"], 1.25)

        invalid = normalize_performance({
            "idle_poll_after_seconds": "nan",
            "idle_poll_interval_seconds": -2,
        })
        self.assertEqual(invalid["idle_poll_after_seconds"], 30.0)
        self.assertEqual(invalid["idle_poll_interval_seconds"], 0.0)
        self.assertEqual(
            debug.adaptive_interval(1.0, invalid["idle_poll_after_seconds"],
                                    invalid["idle_poll_interval_seconds"], 0, 40),
            1.0,
        )


if __name__ == "__main__":
    unittest.main()
