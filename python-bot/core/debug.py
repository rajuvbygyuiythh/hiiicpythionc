"""Low-noise runtime diagnostics for the EVA bot.

Set ``EVA_DEBUG=1`` to enable per-phase timings and traceback details. The
helpers are deliberately safe to call from browser and GUI hot paths: logging
failures never replace the original application error, and sensitive values
in diagnostic text are redacted before they reach a log sink.
"""

from __future__ import annotations

import math
import os
import re
import time
import traceback
from contextlib import contextmanager
from typing import Any, Callable, Iterator

_DEBUG_TRUE = ("1", "true", "yes", "on")

_SECRET_ASSIGNMENT = re.compile(
    r"""(?ix)
    (\b(?:password|passwd|pwd|secret|api[_-]?key|access[_-]?token|
        refresh[_-]?token|token|csrf[_-]?token|session(?:[_-]?(?:id|token))?|
        cookie|authorization|x-auth-token|x-api-key)\b\s*[:=]\s*)
    (?!\[REDACTED\])
    (?:Bearer\s+)?
    (?:"[^"]*"|'[^']*'|[^\s,;&}\]]+)
    """
)
_COOKIE_HEADER = re.compile(r"(?im)(\b(?:cookie|set-cookie)\b\s*:\s*)[^\r\n]*")
_BEARER_TOKEN = re.compile(r"(?i)(\bBearer\s+)[A-Za-z0-9._~+/=-]+")
_URL_CREDENTIALS = re.compile(r"(?i)(https?://)[^/@\s:]+:[^/@\s]+@")


def is_debug() -> bool:
    """Return whether ``EVA_DEBUG`` enables verbose diagnostics."""
    try:
        return str(os.environ.get("EVA_DEBUG", "")).strip().lower() in _DEBUG_TRUE
    except Exception:
        return False


def redact_secrets(value: Any) -> str:
    """Mask common credential forms without changing ordinary diagnostic text."""
    try:
        text = str(value)
    except Exception:
        text = "<unprintable diagnostic value>"
    text = _URL_CREDENTIALS.sub(r"\1[REDACTED]@", text)
    text = _SECRET_ASSIGNMENT.sub(r"\1[REDACTED]", text)
    text = _COOKIE_HEADER.sub(r"\1[REDACTED]", text)
    return _BEARER_TOKEN.sub(r"\1[REDACTED]", text)


def _emit(log_fn: Callable[[str], None], message: Any) -> None:
    try:
        log_fn(redact_secrets(message))
    except Exception:
        pass


def dbg(log_fn: Callable[[str], None], msg: str) -> None:
    """Log *msg* only when debug is enabled. Never raises."""
    try:
        if is_debug():
            _emit(log_fn, msg)
    except Exception:
        pass


@contextmanager
def timed(log_fn: Callable[[str], None], label: str,
          threshold_ms: float = 0.0) -> Iterator[None]:
    """Log ``[T] <label>: <ms>ms`` for a block while debug is enabled.

    Blocks below *threshold_ms* remain silent. Exceptions from the wrapped
    block propagate normally; timing/logging errors are ignored.
    """
    started = time.monotonic()
    try:
        yield
    finally:
        try:
            if is_debug():
                threshold = float(threshold_ms)
                if not math.isfinite(threshold) or threshold < 0:
                    threshold = 0.0
                elapsed_ms = (time.monotonic() - started) * 1000.0
                if elapsed_ms >= threshold:
                    _emit(log_fn, f"[T] {label}: {elapsed_ms:.1f}ms")
        except Exception:
            pass


def exc(log_fn: Callable[[str], None], label: str, error: BaseException) -> None:
    """Always log a concise error; add its traceback only in debug mode.

    The traceback is formatted from the supplied exception rather than the
    ambient ``except`` block, so callers may safely log a saved exception later.
    """
    try:
        error_name = type(error).__name__
        _emit(log_fn, f"{label}: {error_name}: {error}")
    except Exception:
        pass

    try:
        if not is_debug():
            return
        lines = traceback.format_exception(type(error), error, error.__traceback__)
        # Bound the UI/log volume while keeping the innermost frames and the
        # exception line that identify the failure.
        for line in lines[-16:]:
            if line.strip():
                _emit(log_fn, f"[Dbg] {label} | {line.strip()}")
        if not error.__traceback__:
            _emit(log_fn, f"[Dbg] {label} | traceback unavailable (exception was not raised)")
    except Exception:
        pass


def _finite_float(value: Any, fallback: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return fallback
    return number if math.isfinite(number) else fallback


def adaptive_interval(base: Any, idle_after: Any, idle_value: Any,
                      last_active: Any, now: Any) -> float:
    """Return the active poll gap or a slower gap after an idle period.

    This helper is pure so timing policy can be tested without mocking a clock.
    Invalid/non-finite inputs fall back to a safe active interval.
    """
    base_gap = _finite_float(base, 0.5)
    if base_gap <= 0:
        base_gap = 0.5

    idle_after_seconds = _finite_float(idle_after, math.inf)
    if idle_after_seconds < 0:
        idle_after_seconds = math.inf
    idle_gap = _finite_float(idle_value, base_gap)
    if idle_gap <= 0:
        idle_gap = base_gap

    now_seconds = _finite_float(now, math.nan)
    last_active_seconds = _finite_float(last_active, math.nan)
    if not math.isfinite(now_seconds) or not math.isfinite(last_active_seconds):
        return base_gap
    if now_seconds - last_active_seconds >= idle_after_seconds:
        return idle_gap
    return base_gap


__all__ = ["is_debug", "redact_secrets", "dbg", "timed", "exc", "adaptive_interval"]
