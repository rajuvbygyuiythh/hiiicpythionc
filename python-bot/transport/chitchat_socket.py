"""Browserless Socket.IO observer built only from captured protocol details.

This module opens a WebSocket-only Socket.IO connection from an existing saved
browser session. It does not start matchmaking or send chat messages: those
outbound business events are intentionally left unconfigured until captured.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_ENDPOINT = "https://api.chitchat.gg"
DEFAULT_ORIGIN = "https://app.chitchat.gg"
DEFAULT_SOCKETIO_PATH = "socket.io"
# The capture exposes a `release` field, but not its scalar value. Do not guess it.
DEFAULT_RELEASE = ""
OBSERVED_SERVER_EVENTS = (
    "onlineFriends",
    "matchUpdate",
    "typing",
    "chatMessage",
)
_SAFE_KEY_RE = re.compile(r"[^A-Za-z0-9_$.-]+")


class SocketTransportError(RuntimeError):
    """Raised when saved session data cannot be used for a socket connection."""


def load_storage_state(account):
    """Read the existing Playwright storage-state file for a saved account."""
    if not isinstance(account, dict):
        raise SocketTransportError("A saved account mapping is required")
    path = Path(str(account.get("storage_state_path") or ""))
    if not path.is_file():
        raise SocketTransportError("Saved account storage state is missing")
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, TypeError) as error:
        raise SocketTransportError("Saved account storage state is unreadable") from error
    if not isinstance(state, dict):
        raise SocketTransportError("Saved account storage state has an invalid format")
    return state


def _domain_matches(cookie_domain, hostname):
    raw_domain = str(cookie_domain or "").strip().lower()
    host = str(hostname or "").strip().lower()
    if not raw_domain or not host:
        return False
    if raw_domain.startswith("."):
        domain = raw_domain[1:]
        return bool(domain and (host == domain or host.endswith("." + domain)))
    # A host-only cookie (no leading dot in Playwright storage state) must not
    # be widened to subdomains.
    return host == raw_domain


def _path_matches(cookie_path, request_path):
    path = str(cookie_path or "/")
    request = str(request_path or "/")
    if not request.startswith(path):
        return False
    return path.endswith("/") or len(request) == len(path) or request[len(path)] == "/"


def cookie_header_from_storage_state(storage_state, endpoint=DEFAULT_ENDPOINT, socketio_path=DEFAULT_SOCKETIO_PATH, *, now=None):
    """Select only unexpired cookies scoped to this socket host/path."""
    if not isinstance(storage_state, dict):
        return ""
    try:
        parsed = urlsplit(endpoint)
        hostname = parsed.hostname or ""
        secure_connection = parsed.scheme.lower() in {"https", "wss"}
    except (TypeError, ValueError):
        return ""
    request_path = "/" + str(socketio_path or DEFAULT_SOCKETIO_PATH).strip("/") + "/"
    current_time = time.time() if now is None else float(now)
    parts = []
    for cookie in storage_state.get("cookies", []):
        if not isinstance(cookie, dict):
            continue
        name = str(cookie.get("name") or "").strip()
        value = str(cookie.get("value") or "")
        if (
            not name
            or any(char in name for char in " ;=,\t\r\n")
            or any(char in value for char in ";\r\n")
            or not _domain_matches(cookie.get("domain"), hostname)
        ):
            continue
        if not _path_matches(cookie.get("path"), request_path):
            continue
        if cookie.get("secure") and not secure_connection:
            continue
        try:
            expiry = float(cookie.get("expires", -1))
        except (TypeError, ValueError):
            expiry = -1
        if expiry > 0 and expiry <= current_time:
            continue
        parts.append(f"{name}={value}")
    return "; ".join(parts)


def local_storage_value(storage_state, key, origin=DEFAULT_ORIGIN):
    """Return one explicitly named localStorage value; never guess token keys."""
    wanted_key = str(key or "").strip()
    if not wanted_key or not isinstance(storage_state, dict):
        return None
    for entry in storage_state.get("origins", []):
        if not isinstance(entry, dict) or entry.get("origin") != origin:
            continue
        for item in entry.get("localStorage", []):
            if isinstance(item, dict) and item.get("name") == wanted_key:
                value = item.get("value")
                return str(value) if value is not None else None
    return None


def summarize_payload_shape(payload):
    """Return event payload type/keys only; do not include scalar values."""
    if isinstance(payload, dict):
        keys = [
            _SAFE_KEY_RE.sub("_", str(key)).strip("_")[:64]
            for key in list(payload)[:40]
        ]
        return f"object keys={keys}"
    if isinstance(payload, list):
        return f"array length={len(payload)}"
    if payload is None:
        return "null"
    if isinstance(payload, bool):
        return "boolean"
    if isinstance(payload, (int, float)):
        return "number"
    if isinstance(payload, str):
        return "string"
    return "other"


class ChitchatSocketTransport:
    """Connect with saved session material and expose only observed server events."""

    def __init__(
        self,
        account,
        *,
        endpoint=DEFAULT_ENDPOINT,
        origin=DEFAULT_ORIGIN,
        socketio_path=DEFAULT_SOCKETIO_PATH,
        release=DEFAULT_RELEASE,
        token_storage_key=None,
        token_prefix="",
        authorization_value=None,
        client=None,
        logger=None,
        connect_timeout=12,
    ):
        self.account = account
        self.endpoint = str(endpoint).strip()
        self.origin = str(origin).strip()
        self.socketio_path = str(socketio_path).strip("/") or DEFAULT_SOCKETIO_PATH
        self.release = str(release or "").strip()
        self.token_storage_key = str(token_storage_key or "").strip()
        self.token_prefix = str(token_prefix or "")
        self.authorization_value = authorization_value
        self.client = client
        self.logger = logger or (lambda _message: None)
        self.connect_timeout = max(1, int(connect_timeout))
        self._handlers = {}
        self._registered = False

    def on(self, event_name, callback):
        """Register an in-memory callback for a server event."""
        if event_name not in OBSERVED_SERVER_EVENTS:
            raise ValueError(f"Unobserved server event: {event_name}")
        if not callable(callback):
            raise TypeError("event callback must be callable")
        self._handlers.setdefault(event_name, []).append(callback)
        return self

    def _build_client(self):
        if self.client is not None:
            return self.client
        try:
            import socketio
        except ImportError as error:
            raise SocketTransportError(
                "python-socketio is required; install data/requirements.txt"
            ) from error
        self.client = socketio.Client(
            reconnection=True,
            reconnection_attempts=5,
            reconnection_delay=1,
            reconnection_delay_max=8,
            logger=False,
            engineio_logger=False,
        )
        return self.client

    def build_headers(self, storage_state=None):
        """Build handshake headers in memory, without logging credential values."""
        state = storage_state if storage_state is not None else load_storage_state(self.account)
        headers = {"Origin": self.origin}
        cookie = cookie_header_from_storage_state(
            state,
            endpoint=self.endpoint,
            socketio_path=self.socketio_path,
        )
        if cookie:
            headers["Cookie"] = cookie

        authorization = self.authorization_value
        if authorization is None:
            authorization = os.environ.get("CHITCHAT_AUTHORIZATION")
        if authorization:
            headers["Authorization"] = str(authorization)
        elif self.token_storage_key:
            token = local_storage_value(state, self.token_storage_key, origin=self.origin)
            if token:
                headers["Authorization"] = f"{self.token_prefix}{token}"
        return headers

    def _dispatch(self, event_name, *args):
        payload = args[0] if len(args) == 1 else (args if args else None)
        for callback in tuple(self._handlers.get(event_name, ())):
            try:
                callback(payload)
            except Exception as error:
                self.logger(
                    f"[Socket] {event_name} callback failed ({type(error).__name__})"
                )

    def _on_connect(self):
        self.logger("[Socket] Connected using WebSocket transport")
        try:
            self.client.emit("presenceSync")
            self.logger("[Socket] Sent observed presenceSync event")
        except Exception as error:
            self.logger(f"[Socket] presenceSync failed ({type(error).__name__})")

    def _on_disconnect(self, *_args):
        self.logger("[Socket] Disconnected")

    def _on_connect_error(self, *_args):
        self.logger("[Socket] Connection was rejected or failed; details suppressed")

    def connect(self):
        """Open a WebSocket-only Socket.IO connection and send presenceSync."""
        if not self.release:
            raise SocketTransportError(
                "Set the observed Socket.IO release value explicitly; it is not in the capture notes"
            )
        storage_state = load_storage_state(self.account)
        client = self._build_client()
        if not self._registered:
            client.on("connect", self._on_connect)
            client.on("disconnect", self._on_disconnect)
            client.on("connect_error", self._on_connect_error)
            for event_name in OBSERVED_SERVER_EVENTS:
                client.on(
                    event_name,
                    lambda *args, _name=event_name: self._dispatch(_name, *args),
                )
            self._registered = True

        headers = self.build_headers(storage_state)
        auth = {"release": self.release}
        try:
            endpoint_host = urlsplit(self.endpoint).hostname or "unknown host"
        except (TypeError, ValueError):
            endpoint_host = "unknown host"
        self.logger(
            f"[Socket] Connecting to {endpoint_host} with WebSocket-only transport; "
            f"saved cookies={'yes' if 'Cookie' in headers else 'no'}, "
            f"authorization={'yes' if 'Authorization' in headers else 'no'}"
        )
        client.connect(
            self.endpoint,
            headers=headers,
            auth=auth,
            transports=["websocket"],
            socketio_path=self.socketio_path,
            wait=True,
            wait_timeout=self.connect_timeout,
        )
        return client.connected

    def wait(self):
        """Block the caller while the socket client is active."""
        if self.client is None:
            raise SocketTransportError("Connect before waiting for socket events")
        self.client.wait()

    def disconnect(self):
        """Close the socket without issuing any matchmaking/chat action."""
        if self.client is not None and getattr(self.client, "connected", False):
            self.client.disconnect()
