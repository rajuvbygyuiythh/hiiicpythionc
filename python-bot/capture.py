"""Local, metadata-only CDP capture for manual ChitChat protocol diagnostics.

This tool deliberately does NOT persist cookie/token/header values, account
IDs, or message bodies. It captures useful protocol names and payload shapes.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import queue
import re
import sys
import threading
import time
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from browser.socket_trace import (  # noqa: E402
    MAX_FRAME_BYTES,
    MAX_HTTP_BODY_BYTES,
    MAX_SHAPE_NODES,
    _append_shape,
    _body_shape,
    _url_metadata,
    summarize_frame,
)

MAX_CAPTURE_BYTES = 5_000_000
MAX_TRACKED_REQUESTS = 10_000
MAX_TRACKED_WEBSOCKETS = 2_000
MAX_QUEUED_CDP_EVENTS = 2_000
MAX_STORAGE_ITEMS = 200
MAX_IDB_DATABASES = 100
CDP_COMMAND_TIMEOUT_SECONDS = 15
SENSITIVE_NAME_MARKERS = (
    "auth", "token", "cookie", "session", "secret", "password", "credential",
    "uid", "user_id", "userid", "email",
)
_KEY_RE = re.compile(r"[^A-Za-z0-9_$.-]+")
_EMAIL_RE = re.compile(r"^[^/@]+@[^/@]+\.[^/@]+$")
_ID_RE = re.compile(r"^(?:[0-9]+|[0-9a-f]{16,}|[0-9a-f]{8}-[0-9a-f-]{27,})$", re.I)
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
_SAFE_SUBDOMAIN_LABELS = {
    "www", "api", "app", "ws", "websocket", "socket", "socketio", "chat",
    "auth", "account", "accounts", "static", "cdn", "assets", "media",
    "images", "img", "realtime", "gateway",
}


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _host(url):
    try:
        return (urlsplit(str(url or "")).hostname or "").lower().rstrip(".")
    except (TypeError, ValueError):
        return ""


def _matches_domain(url, target_domain):
    host = _host(url)
    return bool(host) and (host == target_domain or host.endswith("." + target_domain))


def _safe_key(value, dynamic=False):
    """Keep field names, but mask likely values used as keys/identifiers."""
    text = str(value or "")
    if dynamic or len(text) > 80 or _EMAIL_RE.fullmatch(text) or _ID_RE.fullmatch(text):
        return "{key}"
    return _KEY_RE.sub("_", text).strip("_")[:64]


def _size_bucket(value):
    if value is None:
        return "unknown"
    try:
        size = max(0, int(value))
    except (TypeError, ValueError):
        return "unknown"
    if size == 0:
        return "empty"
    if size <= 32:
        return "1-32"
    if size <= 256:
        return "33-256"
    if size <= 2048:
        return "257-2048"
    if size <= 16384:
        return "2049-16384"
    return "16385+"


def _header_names(headers):
    if not isinstance(headers, dict):
        return []
    return sorted({_safe_key(name).lower() for name in headers if name})[:60]


def _credential_header_names(headers):
    return [
        name for name in _header_names(headers)
        if any(marker in name for marker in SENSITIVE_NAME_MARKERS)
    ][:30]


def _safe_mime_type(value):
    # MIME type only; drop boundaries, charset and all other parameters.
    return re.sub(r"[^a-zA-Z0-9.+/-]", "", str(value or "").split(";", 1)[0])[:100].lower()


def _content_type(headers):
    if not isinstance(headers, dict):
        return ""
    value = next(
        (value for name, value in headers.items() if str(name).lower() == "content-type"),
        "",
    )
    return _safe_mime_type(value)


def _safe_endpoint(url, target_domain):
    if not _matches_domain(url, target_domain):
        return None
    endpoint = _url_metadata(url)
    host = str(endpoint.get("endpoint_host") or "").lower()
    target_domain = target_domain.lower().strip(".")
    if host != target_domain:
        prefix = host[: -(len(target_domain) + 1)]
        labels = prefix.split(".") if prefix else []
        if not labels or any(label not in _SAFE_SUBDOMAIN_LABELS for label in labels):
            endpoint["endpoint_host"] = "{subdomain}." + target_domain
    return endpoint


def _shape_sensitive_names(body_shape):
    """Return field NAMES suggesting auth/identity, never their values."""
    names = set()

    def walk(node):
        if isinstance(node, dict):
            for key in node.get("keys", []):
                key_text = str(key).lower()
                if any(marker in key_text for marker in SENSITIVE_NAME_MARKERS):
                    names.add(_safe_key(key))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(body_shape)
    return sorted(names)[:30]


def summarize_websocket_frame(payload, opcode, direction, endpoint_or_url, target_domain):
    """Describe a WebSocket frame without retaining its payload values."""
    if isinstance(endpoint_or_url, dict):
        endpoint = {
            "endpoint_host": str(endpoint_or_url.get("endpoint_host") or "")[:200],
            "endpoint_path": str(endpoint_or_url.get("endpoint_path") or "/")[:500],
            "query_keys": [str(key)[:64] for key in endpoint_or_url.get("query_keys", [])[:40]],
        }
    else:
        endpoint = _safe_endpoint(endpoint_or_url, target_domain)
    endpoint = endpoint or {"endpoint_host": "", "endpoint_path": "/", "query_keys": []}
    try:
        opcode = int(opcode)
    except (TypeError, ValueError):
        opcode = -1

    if opcode in {8, 9, 10}:
        return {
            "kind": {8: "control_close", 9: "control_ping", 10: "control_pong"}[opcode],
            "direction": direction,
            "frame_bytes": 0,
            **endpoint,
        }
    if opcode != 1 or not isinstance(payload, str):
        encoded_length = len(str(payload or ""))
        # CDP uses base64 for binary frame payloads. Estimate decoded size
        # without decoding or retaining the binary contents.
        decoded_length = max(0, (encoded_length * 3 // 4) - (2 if str(payload).endswith("==") else 1 if str(payload).endswith("=") else 0))
        return {
            "kind": "binary_frame" if opcode == 2 else "unsupported_frame_type",
            "direction": direction,
            "frame_bytes": decoded_length,
            **endpoint,
        }

    # Generic JSON WebSockets are summarized as schema only. Engine.IO /
    # Socket.IO text packets use the existing bounded, value-redacted parser.
    frame_bytes = len(payload.encode("utf-8", errors="replace"))
    if frame_bytes > MAX_FRAME_BYTES:
        return {
            "kind": "oversized_frame",
            "direction": direction,
            "frame_bytes": frame_bytes,
            **endpoint,
        }
    stripped = payload.lstrip()
    if stripped.startswith(("{", "[", '"')):
        try:
            value = json.loads(payload)
        except (TypeError, ValueError, json.JSONDecodeError):
            value = None
            invalid_json = True
        else:
            invalid_json = False
        if not invalid_json:
            shape = []
            _append_shape(value, "payload", shape)
            return {
                "kind": "json_frame",
                "direction": direction,
                "frame_bytes": frame_bytes,
                "data_shape": shape[:MAX_SHAPE_NODES],
                **endpoint,
            }

    safe_url = f"wss://{endpoint['endpoint_host']}{endpoint['endpoint_path']}"
    summary = summarize_frame(payload, direction, safe_url)
    summary.update(endpoint)
    # Unknown text protocols are kept as size/type metadata only. Do not log
    # the frame prefix or any unparsed text.
    if summary.get("kind") == "unknown_engine_packet":
        return {
            "kind": "text_frame",
            "direction": direction,
            "frame_bytes": summary.get("frame_bytes", 0),
            **endpoint,
        }
    return summary


class BoundedJsonlWriter:
    """Append flushed JSONL records, stopping before the configured size cap."""

    def __init__(self, path, max_bytes=MAX_CAPTURE_BYTES):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max(4096, int(max_bytes))
        self._lock = threading.RLock()
        self._sequence = 0
        self._written_bytes = 0
        self.stopped = False
        try:
            descriptor = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise RuntimeError("Capture output already exists; choose a new output directory") from exc
        self._handle = os.fdopen(descriptor, "wb")

    def write(self, record):
        with self._lock:
            if self.stopped:
                return False
            self._sequence += 1
            safe_record = dict(record)
            safe_record.setdefault("timestamp", utc_now())
            safe_record["sequence"] = self._sequence
            line = (json.dumps(safe_record, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
            marker = (json.dumps({
                "source": "capture",
                "kind": "size_limit_reached",
                "timestamp": safe_record["timestamp"],
                "max_bytes": self.max_bytes,
                "sequence": self._sequence + 1,
            }, separators=(",", ":")) + "\n").encode("utf-8")
            if self._written_bytes + len(line) + len(marker) > self.max_bytes:
                if self._written_bytes + len(marker) <= self.max_bytes:
                    self._handle.write(marker)
                    self._handle.flush()
                    self._written_bytes += len(marker)
                self.stopped = True
                return False
            self._handle.write(line)
            self._handle.flush()
            self._written_bytes += len(line)
            return True

    def close(self):
        with self._lock:
            if self._handle and not self._handle.closed:
                self._handle.flush()
                self._handle.close()


class CDPError(RuntimeError):
    def __init__(self, method, code=None):
        self.method = method
        self.code = code
        super().__init__(f"CDP command failed: {method}" + (f" (code {code})" if code is not None else ""))


class CDPClient:
    """Small CDP WebSocket client; CDP payloads are processed locally only."""

    def __init__(self, websocket_url, origin="http://localhost"):
        try:
            import websocket  # websocket-client, declared in data/requirements.txt
        except ImportError as exc:
            raise RuntimeError("Missing CDP dependency; install websocket-client") from exc
        self._websocket_module = websocket
        try:
            self._ws = websocket.create_connection(
                websocket_url,
                timeout=1,
                origin=origin,
                http_no_proxy=list(_LOCAL_HOSTS),
                enable_multithread=True,
            )
            self._ws.settimeout(1)
        except Exception as exc:
            raise RuntimeError(f"Could not connect to local CDP ({type(exc).__name__})") from None
        self._events = queue.Queue(maxsize=MAX_QUEUED_CDP_EVENTS)
        self._pending = {}
        self._lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._next_id = 0
        self._stop = threading.Event()
        self._reader_error = None
        self._reader = threading.Thread(target=self._read_loop, name="cdp-reader", daemon=True)
        self._reader.start()

    def _read_loop(self):
        timeout_error = getattr(self._websocket_module, "WebSocketTimeoutException", ())
        closed_error = getattr(self._websocket_module, "WebSocketConnectionClosedException", ())
        while not self._stop.is_set():
            try:
                raw = self._ws.recv()
            except timeout_error:
                continue
            except closed_error:
                self._reader_error = "connection_closed"
                break
            except Exception as exc:
                self._reader_error = type(exc).__name__
                break
            if not raw:
                self._reader_error = "connection_closed"
                break
            try:
                message = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            message_id = message.get("id")
            if message_id is not None:
                with self._lock:
                    waiter = self._pending.get(message_id)
                if waiter is not None:
                    waiter.put(message)
            else:
                try:
                    self._events.put(message, timeout=0.2)
                except queue.Full:
                    # Bound memory if the site produces a high-frequency stream.
                    self._reader_error = "event_queue_full"
                    break
        try:
            self._events.put_nowait(None)
        except queue.Full:
            pass
        with self._lock:
            pending = list(self._pending.values())
        for waiter in pending:
            try:
                waiter.put_nowait({"_closed": True})
            except queue.Full:
                pass

    def command(self, method, params=None, session_id=None, timeout=CDP_COMMAND_TIMEOUT_SECONDS):
        with self._lock:
            self._next_id += 1
            command_id = self._next_id
            waiter = queue.Queue(maxsize=1)
            self._pending[command_id] = waiter
        message = {"id": command_id, "method": method, "params": params or {}}
        if session_id:
            message["sessionId"] = session_id
        try:
            with self._send_lock:
                self._ws.send(json.dumps(message, separators=(",", ":")))
        except Exception as exc:
            with self._lock:
                self._pending.pop(command_id, None)
            raise RuntimeError(f"CDP send failed ({type(exc).__name__})") from None
        try:
            response = waiter.get(timeout=max(0.1, float(timeout)))
        except queue.Empty:
            with self._lock:
                self._pending.pop(command_id, None)
            raise TimeoutError(f"CDP timeout: {method}") from None
        finally:
            with self._lock:
                self._pending.pop(command_id, None)
        if response.get("_closed"):
            raise RuntimeError("CDP connection closed")
        if "error" in response:
            error = response.get("error") or {}
            raise CDPError(method, error.get("code"))
        return response.get("result") or {}

    def get_event(self, timeout=0.5):
        try:
            return self._events.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self):
        self._stop.set()
        try:
            self._ws.close()
        except Exception:
            pass
        if self._reader.is_alive():
            self._reader.join(timeout=2)


def _local_browser_ws_url(browser_url):
    parsed = urlsplit(browser_url)
    if (
        parsed.scheme not in {"http", "https"}
        or (parsed.hostname or "").lower() not in _LOCAL_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("CDP browser URL must be a plain localhost/loopback origin")
    try:
        browser_port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        raise ValueError("CDP browser URL has an invalid port") from None
    request = Request(
        f"{parsed.scheme}://{parsed.netloc}/json/version",
        headers={"Accept": "application/json"},
    )
    try:
        opener = build_opener(ProxyHandler({}))
        with opener.open(request, timeout=5) as response:
            metadata = json.loads(response.read(256_000).decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"Cannot read local CDP version endpoint ({type(exc).__name__})") from None
    websocket_url = str(metadata.get("webSocketDebuggerUrl") or "")
    ws = urlsplit(websocket_url)
    expected_scheme = "wss" if parsed.scheme == "https" else "ws"
    if (
        ws.scheme != expected_scheme
        or (ws.hostname or "").lower() not in _LOCAL_HOSTS
        or ws.username is not None
        or ws.password is not None
        or ws.fragment
    ):
        raise ValueError("CDP returned a non-loopback WebSocket URL; refusing it")
    try:
        websocket_port = ws.port or (443 if ws.scheme == "wss" else 80)
    except ValueError:
        raise ValueError("CDP WebSocket URL has an invalid port") from None
    if websocket_port != browser_port:
        raise ValueError("CDP WebSocket port does not match the local browser endpoint")
    return websocket_url


def _create_run_directory(base_dir):
    base = Path(base_dir)
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("cdp-%Y%m%dT%H%M%SZ")
    for suffix in range(100):
        candidate = base / (stamp if suffix == 0 else f"{stamp}-{suffix:02d}")
        try:
            candidate.mkdir(mode=0o700)
            return candidate
        except FileExistsError:
            continue
    raise RuntimeError("Could not create a unique capture directory")


_STORAGE_SNAPSHOT_SCRIPT = r"""
(async () => {
  const sizeBucket = n => n === 0 ? 'empty' : n <= 32 ? '1-32' : n <= 256 ? '33-256'
    : n <= 2048 ? '257-2048' : n <= 16384 ? '2049-16384' : '16385+';
  const summarize = storage => {
    const items = [];
    const limit = Math.min(storage.length || 0, 200);
    for (let i = 0; i < limit; i++) {
      const key = storage.key(i) || '';
      const value = storage.getItem(key);
      items.push({key, present: value !== null, size: sizeBucket(value === null ? 0 : value.length)});
    }
    return {count: storage.length || 0, items};
  };
  const cookieNames = (() => {
    try { return (document.cookie || '').split(/;\s*/).filter(Boolean)
      .map(part => part.split('=', 1)[0]).slice(0, 100); }
    catch (_) { return []; }
  })();
  let databases = [];
  try {
    if (indexedDB.databases) {
      databases = (await indexedDB.databases()).slice(0, 100)
        .map(db => ({name: db.name || '', version: db.version || 0}));
    }
  } catch (_) {}
  let local = {count: 0, items: []}, session = {count: 0, items: []};
  try { local = summarize(localStorage); } catch (_) {}
  try { session = summarize(sessionStorage); } catch (_) {}
  return {origin: location.origin, localStorage: local, sessionStorage: session,
          visibleCookieNames: cookieNames, indexedDBDatabases: databases};
})()
"""


class CDPMetadataCapture:
    def __init__(self, client, writer, target_domain):
        self.client = client
        self.writer = writer
        self.target_domain = target_domain
        self._session_info = {}
        self._target_to_session = {}
        self._page_counter = 0
        self._request_counter = 0
        self._websocket_counter = 0
        self._request_map = OrderedDict()
        self._websocket_map = OrderedDict()
        self._started_at = time.monotonic()
        self._auto_attach = False

    def _write(self, record):
        if self.writer.stopped:
            return False
        return self.writer.write(record)

    def initialize(self):
        self.client.command("Target.setDiscoverTargets", {"discover": True})
        try:
            self.client.command("Target.setAutoAttach", {
                "autoAttach": True,
                "waitForDebuggerOnStart": False,
                "flatten": True,
            })
            self._auto_attach = True
        except (CDPError, TimeoutError, RuntimeError):
            self._write({
                "source": "capture", "kind": "auto_attach_unavailable",
                "note": "New tabs may require restarting the capture tool.",
            })

        try:
            targets = self.client.command("Target.getTargets").get("targetInfos", [])
        except Exception:
            targets = []
        for target in targets:
            if target.get("type") == "page":
                self._attach_existing_target(target)

    def _attach_existing_target(self, target_info):
        target_id = target_info.get("targetId")
        if not target_id or target_id in self._target_to_session:
            return
        try:
            result = self.client.command("Target.attachToTarget", {
                "targetId": target_id,
                "flatten": True,
            })
        except (CDPError, TimeoutError, RuntimeError):
            # The auto-attach event may already have claimed this target.
            return
        session_id = result.get("sessionId")
        if session_id:
            self._register_target(session_id, target_info)

    def _register_target(self, session_id, target_info):
        target_id = target_info.get("targetId")
        if target_info.get("type") != "page":
            try:
                self.client.command("Target.detachFromTarget", {"sessionId": session_id})
            except Exception:
                pass
            return
        if target_id and target_id in self._target_to_session:
            existing = self._target_to_session[target_id]
            if existing != session_id:
                try:
                    self.client.command("Target.detachFromTarget", {"sessionId": session_id})
                except Exception:
                    pass
            return
        self._page_counter += 1
        page_id = f"p{self._page_counter}"
        endpoint = _safe_endpoint(target_info.get("url", ""), self.target_domain)
        info = {"page_id": page_id, "target_id": target_id, "endpoint": endpoint}
        self._session_info[session_id] = info
        if target_id:
            self._target_to_session[target_id] = session_id
        for method in ("Page.enable", "Network.enable"):
            try:
                self.client.command(method, session_id=session_id)
            except Exception:
                self._write({
                    "source": "capture", "kind": "cdp_domain_enable_failed",
                    "page_id": page_id, "domain": method.split(".", 1)[0],
                })
        endpoint = info.get("endpoint")
        if endpoint:
            self._write({"source": "page", "kind": "page_attached", "page_id": page_id, **endpoint})
            self._enable_target_metadata(session_id, page_id, snapshot=True)

    def _enable_target_metadata(self, session_id, page_id, snapshot=False):
        info = self._session_info.get(session_id)
        if not info or not info.get("endpoint"):
            return
        if not info.get("metadata_enabled"):
            info["metadata_enabled"] = True
            for method in ("DOMStorage.enable", "Runtime.enable"):
                try:
                    self.client.command(method, session_id=session_id)
                except Exception:
                    self._write({
                        "source": "capture", "kind": "cdp_domain_enable_failed",
                        "page_id": page_id, "domain": method.split(".", 1)[0],
                    })
        if snapshot:
            self._capture_storage_snapshot(session_id, page_id)

    def _new_ref(self, prefix):
        if prefix == "ws":
            self._websocket_counter += 1
            return f"ws{self._websocket_counter}"
        self._request_counter += 1
        return f"r{self._request_counter}"

    def _request_info(self, session_id, cdp_request_id):
        return self._request_map.get((session_id, cdp_request_id))

    def _remember_request(self, session_id, cdp_request_id, info):
        key = (session_id, cdp_request_id)
        self._request_map[key] = info
        self._request_map.move_to_end(key)
        while len(self._request_map) > MAX_TRACKED_REQUESTS:
            self._request_map.popitem(last=False)

    def _page_id(self, session_id):
        return self._session_info.get(session_id, {}).get("page_id", "unknown")

    def _capture_storage_snapshot(self, session_id, page_id):
        try:
            result = self.client.command("Runtime.evaluate", {
                "expression": _STORAGE_SNAPSHOT_SCRIPT,
                "awaitPromise": True,
                "returnByValue": True,
                "timeout": 10_000,
            }, session_id=session_id, timeout=CDP_COMMAND_TIMEOUT_SECONDS)
        except Exception:
            return
        value = (result.get("result") or {}).get("value")
        if not isinstance(value, dict) or not _matches_domain(value.get("origin"), self.target_domain):
            return
        endpoint = _safe_endpoint(value.get("origin"), self.target_domain)
        record = {
            "source": "storage",
            "kind": "storage_snapshot",
            "page_id": page_id,
            "origin_host": endpoint["endpoint_host"],
            "localStorage": self._sanitize_storage(value.get("localStorage")),
            "sessionStorage": self._sanitize_storage(value.get("sessionStorage")),
            "visible_cookie_names": self._sanitize_names(value.get("visibleCookieNames", [])),
            "http_only_cookie_values": "not_inspected",
            "indexedDB_databases": self._sanitize_databases(value.get("indexedDBDatabases", [])),
            "indexedDB_records": "not_inspected",
        }
        self._write(record)

    @staticmethod
    def _sanitize_storage(storage):
        if not isinstance(storage, dict):
            return {"count": 0, "items": []}
        items = []
        for item in storage.get("items", [])[:MAX_STORAGE_ITEMS]:
            if not isinstance(item, dict):
                continue
            key = _safe_key(item.get("key"))
            items.append({
                "key": key,
                "present": bool(item.get("present")),
                "size_bucket": str(item.get("size") or "unknown")[:24],
                "sensitive_key_name": any(marker in key.lower() for marker in SENSITIVE_NAME_MARKERS),
            })
        try:
            count = max(0, min(100_000, int(storage.get("count", 0) or 0)))
        except (TypeError, ValueError):
            count = 0
        return {"count": count, "items": items}

    @staticmethod
    def _sanitize_names(names):
        if not isinstance(names, list):
            return []
        return sorted({_safe_key(name) for name in names if name})[:100]

    @staticmethod
    def _sanitize_databases(databases):
        if not isinstance(databases, list):
            return []
        output = []
        for database in databases[:MAX_IDB_DATABASES]:
            if isinstance(database, dict):
                try:
                    version = max(0, min(1_000_000, int(database.get("version", 0) or 0)))
                except (TypeError, ValueError):
                    version = 0
                output.append({"name": _safe_key(database.get("name")), "version": version})
        return output

    def handle_event(self, message):
        if not isinstance(message, dict):
            return
        method = message.get("method")
        params = message.get("params") or {}
        session_id = message.get("sessionId")
        if method == "Target.attachedToTarget":
            self._register_target(params.get("sessionId"), params.get("targetInfo") or {})
            return
        if method == "Target.targetInfoChanged":
            target = params.get("targetInfo") or {}
            target_id = target.get("targetId")
            session = self._target_to_session.get(target_id)
            if session in self._session_info:
                endpoint = _safe_endpoint(target.get("url", ""), self.target_domain)
                self._session_info[session]["endpoint"] = endpoint
                if endpoint:
                    self._enable_target_metadata(session, self._page_id(session), snapshot=True)
            return
        if method == "Target.detachedFromTarget":
            detached = params.get("sessionId")
            info = self._session_info.pop(detached, None)
            if info and info.get("target_id"):
                self._target_to_session.pop(info["target_id"], None)
                for key in list(self._request_map):
                    if key[0] == detached:
                        self._request_map.pop(key, None)
                for key in list(self._websocket_map):
                    if key[0] == detached:
                        self._websocket_map.pop(key, None)
                self._write({
                    "source": "page", "kind": "page_detached",
                    "page_id": info["page_id"],
                })
            return
        if method == "Page.frameNavigated":
            self._handle_navigation(session_id, params.get("frame") or {})
            return
        if method and method.startswith("DOMStorage."):
            self._handle_dom_storage(session_id, method, params)
            return
        if not method or not method.startswith("Network."):
            return
        if method == "Network.requestWillBeSent":
            self._handle_request(session_id, params)
        elif method == "Network.responseReceived":
            self._handle_response(session_id, params)
        elif method == "Network.requestWillBeSentExtraInfo":
            self._handle_extra_request_headers(session_id, params)
        elif method == "Network.responseReceivedExtraInfo":
            self._handle_extra_response_headers(session_id, params)
        elif method == "Network.loadingFinished":
            self._handle_loading_finished(session_id, params)
        elif method == "Network.loadingFailed":
            self._handle_loading_failed(session_id, params)
        elif method == "Network.webSocketCreated":
            self._handle_websocket_created(session_id, params)
        elif method == "Network.webSocketWillSendHandshakeRequest":
            self._handle_websocket_handshake_request(session_id, params)
        elif method == "Network.webSocketHandshakeResponseReceived":
            self._handle_websocket_handshake_response(session_id, params)
        elif method in {"Network.webSocketFrameSent", "Network.webSocketFrameReceived"}:
            self._handle_websocket_frame(session_id, method, params)
        elif method == "Network.webSocketFrameError":
            self._handle_websocket_error(session_id, params)
        elif method == "Network.webSocketClosed":
            self._handle_websocket_closed(session_id, params)

    def _handle_navigation(self, session_id, frame):
        if frame.get("parentId"):
            return
        url = frame.get("url", "")
        endpoint = _safe_endpoint(url, self.target_domain)
        if not endpoint:
            return
        page_id = self._page_id(session_id)
        if session_id in self._session_info:
            self._session_info[session_id]["endpoint"] = endpoint
        self._write({"source": "page", "kind": "main_frame_navigation", "page_id": page_id, **endpoint})
        self._enable_target_metadata(session_id, page_id, snapshot=True)

    def _handle_dom_storage(self, session_id, method, params):
        storage_id = params.get("storageId") or {}
        origin = storage_id.get("securityOrigin", "")
        if not _matches_domain(origin, self.target_domain):
            return
        operation = method.rsplit(".", 1)[-1]
        if operation == "domStorageItemsCleared":
            details = {"cleared": True}
        elif operation == "domStorageItemRemoved":
            details = {"key": _safe_key(params.get("key")), "value_present": False}
        elif operation == "domStorageItemAdded":
            value = params.get("newValue")
            details = {
                "key": _safe_key(params.get("key")),
                "value_present": value is not None,
                "value_size_bucket": _size_bucket(None if value is None else len(str(value))),
            }
        elif operation == "domStorageItemUpdated":
            value = params.get("newValue")
            details = {
                "key": _safe_key(params.get("key")),
                "value_present": value is not None,
                "value_size_bucket": _size_bucket(None if value is None else len(str(value))),
            }
        else:
            return
        self._write({
            "source": "storage",
            "kind": "storage_change",
            "page_id": self._page_id(session_id),
            "storage_area": "localStorage" if storage_id.get("isLocalStorage") else "sessionStorage",
            "operation": operation,
            **details,
        })

    def _handle_request(self, session_id, params):
        request = params.get("request") or {}
        url = request.get("url", "")
        endpoint = _safe_endpoint(url, self.target_domain)
        resource_type = str(params.get("type") or "Other")
        headers = request.get("headers") or {}
        cdp_request_id = params.get("requestId")
        if not endpoint or resource_type not in {"XHR", "Fetch", "WebSocket", "Document"}:
            if cdp_request_id is not None:
                key = (session_id, cdp_request_id)
                self._request_map.pop(key, None)
                self._websocket_map.pop(key, None)
            return
        previous = self._request_info(session_id, cdp_request_id)
        request_ref = previous.get("request_ref") if previous else self._new_ref("r")
        method = str(request.get("method") or "GET").upper()[:16]
        mime = _content_type(headers)
        request_body = _body_shape(request.get("postData"), mime) if request.get("postData") is not None else {"type": "empty"}
        info = {
            "request_ref": request_ref,
            "endpoint": endpoint,
            "resource_type": resource_type,
            "method": method,
            "request_timestamp": params.get("timestamp"),
            "response_timestamp": None,
            "response_content_type": "",
            "response_content_length": None,
            "response_status": None,
        }
        self._remember_request(session_id, cdp_request_id, info)
        kind = "websocket_request" if resource_type == "WebSocket" else "api_request"
        self._write({
            "source": "network",
            "kind": kind,
            "page_id": self._page_id(session_id),
            "request_ref": request_ref,
            "method": method,
            "resource_type": resource_type,
            **endpoint,
            "header_names": _header_names(headers),
            "credential_header_names": _credential_header_names(headers),
            "content_type": mime,
            "request_body_shape": request_body,
            "sensitive_body_field_names": _shape_sensitive_names(request_body),
            "redirect_status": (params.get("redirectResponse") or {}).get("status"),
        })

    def _handle_response(self, session_id, params):
        response = params.get("response") or {}
        cdp_request_id = params.get("requestId")
        info = self._request_info(session_id, cdp_request_id)
        url = response.get("url", "")
        endpoint = _safe_endpoint(url, self.target_domain) if url else (info or {}).get("endpoint")
        if not endpoint:
            if url and cdp_request_id is not None:
                key = (session_id, cdp_request_id)
                self._request_map.pop(key, None)
                self._websocket_map.pop(key, None)
            return
        headers = response.get("headers") or {}
        try:
            raw_content_length = next(
                (value for name, value in headers.items() if str(name).lower() == "content-length"),
                None,
            )
            content_length = max(0, int(raw_content_length)) if raw_content_length is not None else None
        except (TypeError, ValueError):
            content_length = None
        content_type = _content_type(headers) or _safe_mime_type(response.get("mimeType"))
        if info is None:
            info = {
                "request_ref": self._new_ref("r"), "endpoint": endpoint,
                "resource_type": str(params.get("type") or "Other"),
                "method": "UNKNOWN", "request_timestamp": None,
            }
            self._remember_request(session_id, cdp_request_id, info)
        info["response_timestamp"] = params.get("timestamp")
        info["response_content_type"] = content_type
        info["response_content_length"] = content_length
        info["response_status"] = response.get("status")
        elapsed = self._elapsed_ms(info.get("request_timestamp"), params.get("timestamp"))
        self._write({
            "source": "network",
            "kind": "api_response" if info.get("resource_type") != "WebSocket" else "websocket_handshake_response",
            "page_id": self._page_id(session_id),
            "request_ref": info["request_ref"],
            "resource_type": info.get("resource_type"),
            "method": info.get("method"),
            **endpoint,
            "status": response.get("status"),
            "elapsed_ms": elapsed,
            "protocol": str(response.get("protocol") or "")[:16],
            "from_disk_cache": bool(response.get("fromDiskCache")),
            "from_service_worker": bool(response.get("fromServiceWorker")),
            "header_names": _header_names(headers),
            "credential_header_names": _credential_header_names(headers),
            "content_type": content_type,
            "response_body_shape": {"type": "followup_event"},
        })

    @staticmethod
    def _elapsed_ms(start, end):
        try:
            return round(max(0.0, float(end) - float(start)) * 1000, 2)
        except (TypeError, ValueError):
            return None

    def _handle_extra_request_headers(self, session_id, params):
        info = self._request_info(session_id, params.get("requestId"))
        if info is None or not info.get("endpoint"):
            return
        headers = params.get("headers") or {}
        self._write({
            "source": "network",
            "kind": "request_headers_extra_metadata",
            "page_id": self._page_id(session_id),
            "request_ref": info["request_ref"],
            "header_names": _header_names(headers),
            "credential_header_names": _credential_header_names(headers),
            "associated_cookie_names": self._cookie_names_from_associations(params.get("associatedCookies", [])),
        })

    @staticmethod
    def _cookie_names_from_associations(items):
        if not isinstance(items, list):
            return []
        names = []
        for item in items[:100]:
            cookie = item.get("cookie") if isinstance(item, dict) else None
            if isinstance(cookie, dict) and cookie.get("name"):
                names.append(_safe_key(cookie.get("name")))
        return names

    def _handle_extra_response_headers(self, session_id, params):
        info = self._request_info(session_id, params.get("requestId"))
        if info is None or not info.get("endpoint"):
            return
        headers = params.get("headers") or {}
        self._write({
            "source": "network",
            "kind": "response_headers_extra_metadata",
            "page_id": self._page_id(session_id),
            "request_ref": info["request_ref"],
            "status": params.get("statusCode"),
            "header_names": _header_names(headers),
            "credential_header_names": _credential_header_names(headers),
        })

    def _handle_loading_finished(self, session_id, params):
        info = self._request_info(session_id, params.get("requestId"))
        if info is None or info.get("resource_type") not in {"XHR", "Fetch"}:
            return
        mime = str(info.get("response_content_type") or "").lower()
        content_length = info.get("response_content_length")
        if not ("json" in mime or mime == "application/x-www-form-urlencoded"):
            return
        if content_length is not None and content_length > MAX_HTTP_BODY_BYTES:
            body_shape = {"type": "omitted_large"}
        else:
            try:
                result = self.client.command("Network.getResponseBody", {
                    "requestId": params.get("requestId"),
                }, session_id=session_id, timeout=CDP_COMMAND_TIMEOUT_SECONDS)
                body = result.get("body", "")
                if result.get("base64Encoded"):
                    if len(body) > ((MAX_HTTP_BODY_BYTES + 2) // 3) * 4 + 8:
                        body_shape = {"type": "omitted_large"}
                    else:
                        raw = base64.b64decode(body, validate=False)
                        body_shape = _body_shape(raw, mime)
                elif len(str(body).encode("utf-8", errors="replace")) > MAX_HTTP_BODY_BYTES:
                    body_shape = {"type": "omitted_large"}
                else:
                    body_shape = _body_shape(body, mime)
            except Exception:
                body_shape = {"type": "unavailable"}
        self._write({
            "source": "network",
            "kind": "response_body_shape",
            "page_id": self._page_id(session_id),
            "request_ref": info["request_ref"],
            "status": info.get("response_status"),
            "body_shape": body_shape,
            "sensitive_body_field_names": _shape_sensitive_names(body_shape),
        })

    def _handle_loading_failed(self, session_id, params):
        info = self._request_info(session_id, params.get("requestId"))
        if info is None:
            return
        self._write({
            "source": "network",
            "kind": "request_failed",
            "page_id": self._page_id(session_id),
            "request_ref": info["request_ref"],
            "method": info.get("method"),
            "resource_type": info.get("resource_type"),
            **(info.get("endpoint") or {}),
            "elapsed_ms": self._elapsed_ms(info.get("request_timestamp"), params.get("timestamp")),
            "failure": True,
        })

    def _ws_info(self, session_id, request_id, endpoint=None):
        key = (session_id, request_id)
        info = self._websocket_map.get(key)
        if info is None:
            self._websocket_counter += 1
            info = {"websocket_id": f"ws{self._websocket_counter}", "endpoint": endpoint}
            self._websocket_map[key] = info
        elif endpoint:
            info["endpoint"] = endpoint
        self._websocket_map.move_to_end(key)
        while len(self._websocket_map) > MAX_TRACKED_WEBSOCKETS:
            self._websocket_map.popitem(last=False)
        return info

    def _handle_websocket_created(self, session_id, params):
        endpoint = _safe_endpoint(params.get("url", ""), self.target_domain)
        if not endpoint:
            return
        info = self._ws_info(session_id, params.get("requestId"), endpoint)
        self._write({
            "source": "websocket",
            "kind": "websocket_created",
            "page_id": self._page_id(session_id),
            "websocket_id": info["websocket_id"],
            **endpoint,
        })

    def _handle_websocket_handshake_request(self, session_id, params):
        cdp_request_id = params.get("requestId")
        request_info = self._request_info(session_id, cdp_request_id) or {}
        ws_info = self._websocket_map.get((session_id, cdp_request_id)) or {}
        endpoint = request_info.get("endpoint") or ws_info.get("endpoint")
        if not endpoint:
            return
        ws_info = self._ws_info(session_id, cdp_request_id, endpoint)
        request = params.get("request") or {}
        headers = request.get("headers") or {}
        self._write({
            "source": "websocket",
            "kind": "websocket_handshake_request",
            "page_id": self._page_id(session_id),
            "websocket_id": ws_info["websocket_id"],
            "method": request_info.get("method", "GET"),
            **endpoint,
            "header_names": _header_names(headers),
            "credential_header_names": _credential_header_names(headers),
            "header_order": "not_recorded",
            "header_values": "redacted",
        })

    def _handle_websocket_handshake_response(self, session_id, params):
        cdp_request_id = params.get("requestId")
        request_info = self._request_info(session_id, cdp_request_id) or {}
        ws_info = self._websocket_map.get((session_id, cdp_request_id)) or {}
        endpoint = request_info.get("endpoint") or ws_info.get("endpoint")
        if not endpoint:
            return
        response = params.get("response") or {}
        headers = response.get("headers") or {}
        ws_info = self._ws_info(session_id, cdp_request_id, endpoint)
        self._write({
            "source": "websocket",
            "kind": "websocket_handshake_response",
            "page_id": self._page_id(session_id),
            "websocket_id": ws_info["websocket_id"],
            **endpoint,
            "status": response.get("status"),
            "header_names": _header_names(headers),
            "credential_header_names": _credential_header_names(headers),
            "header_values": "redacted",
        })

    def _handle_websocket_frame(self, session_id, method, params):
        cdp_request_id = params.get("requestId")
        ws_info = self._websocket_map.get((session_id, cdp_request_id)) or {}
        request_info = self._request_info(session_id, cdp_request_id) or {}
        endpoint = ws_info.get("endpoint") or request_info.get("endpoint")
        if not endpoint:
            return
        response = params.get("response") or {}
        direction = "out" if method.endswith("Sent") else "in"
        summary = summarize_websocket_frame(
            response.get("payloadData", ""),
            response.get("opcode"),
            direction,
            endpoint,
            self.target_domain,
        )
        frame_kind = summary.get("kind", "unknown")
        summary.update({
            "source": "websocket",
            "kind": "websocket_frame",
            "page_id": self._page_id(session_id),
            "websocket_id": ws_info.get("websocket_id", "unknown"),
            "frame_kind": frame_kind,
        })
        self._write(summary)

    def _handle_websocket_error(self, session_id, params):
        request_id = params.get("requestId")
        info = self._websocket_map.get((session_id, request_id)) or {}
        request_info = self._request_info(session_id, request_id) or {}
        endpoint = info.get("endpoint") or request_info.get("endpoint")
        if endpoint:
            self._write({
                "source": "websocket", "kind": "websocket_frame_error",
                "page_id": self._page_id(session_id),
                "websocket_id": info.get("websocket_id", "unknown"), **endpoint,
                "error_details": "omitted",
            })

    def _handle_websocket_closed(self, session_id, params):
        request_id = params.get("requestId")
        info = self._websocket_map.get((session_id, request_id)) or {}
        request_info = self._request_info(session_id, request_id) or {}
        endpoint = info.get("endpoint") or request_info.get("endpoint")
        if endpoint:
            self._write({
                "source": "websocket", "kind": "websocket_closed",
                "page_id": self._page_id(session_id),
                "websocket_id": info.get("websocket_id", "unknown"), **endpoint,
            })



def _validate_args(parser, args):
    target_domain = args.target_domain.lower().strip().strip(".")
    if not target_domain or not re.fullmatch(r"[a-z0-9.-]+", target_domain):
        parser.error("--target-domain must be a DNS name such as chitchat.gg")
    browser = urlsplit(args.browser_url)
    if (
        browser.scheme not in {"http", "https"}
        or (browser.hostname or "").lower() not in _LOCAL_HOSTS
        or browser.username is not None
        or browser.password is not None
        or browser.path not in {"", "/"}
        or browser.query
        or browser.fragment
    ):
        parser.error("--browser-url must be a plain localhost/loopback origin; do not expose CDP to a network")
    origin = urlsplit(args.origin)
    if (
        origin.scheme not in {"http", "https"}
        or (origin.hostname or "").lower() not in _LOCAL_HOSTS
        or origin.username is not None
        or origin.password is not None
        or origin.path not in {"", "/"}
        or origin.query
        or origin.fragment
    ):
        parser.error("--origin must be a plain localhost origin")
    try:
        browser.port
        origin.port
    except ValueError:
        parser.error("--browser-url and --origin must use valid ports")
    if args.duration < 0:
        parser.error("--duration must be >= 0 (0 means until Ctrl+C)")
    if args.max_mb < 1 or args.max_mb > 100:
        parser.error("--max-mb must be between 1 and 100")
    return target_domain


def _parser():
    parser = argparse.ArgumentParser(
        description=(
            "Attach to a local Chromium CDP endpoint and capture redacted "
            "WebSocket/API metadata while you use ChitChat manually."
        )
    )
    parser.add_argument("--browser-url", default="http://127.0.0.1:9222", help="Local Chromium remote-debugging URL")
    parser.add_argument("--origin", default="http://localhost", help="Local origin allowed by Chromium")
    parser.add_argument("--target-domain", default="chitchat.gg", help="Domain to capture; subdomains included")
    parser.add_argument("--output-dir", default=str(ROOT / "capture"), help="Parent directory for this run's output")
    parser.add_argument("--duration", type=int, default=300, help="Seconds to capture (0 = until stopped; default 300)")
    parser.add_argument("--max-mb", type=int, default=5, help="Maximum JSONL size in MB (1-100)")
    parser.add_argument("--stop-file", default="", help="Optional local file whose creation requests a graceful stop")
    return parser


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    target_domain = _validate_args(parser, args)
    writer = None
    client = None
    capture = None
    run_dir = None
    succeeded = False
    started = time.monotonic()
    try:
        websocket_url = _local_browser_ws_url(args.browser_url)
        run_dir = _create_run_directory(args.output_dir)
        writer = BoundedJsonlWriter(run_dir / "capture.jsonl", args.max_mb * 1_000_000)
        writer.write({
            "source": "capture",
            "kind": "capture_started",
            "schema": "cdp-redacted-metadata-v1",
            "target_domain": target_domain,
            "started_at": utc_now(),
            "privacy": "raw_payloads_and_credential_values_not_saved",
        })
        client = CDPClient(websocket_url, origin=args.origin)
        capture = CDPMetadataCapture(client, writer, target_domain)
        started = capture._started_at
        print(f"Output: {run_dir / 'capture.jsonl'}", flush=True)
        print("Capture is live. Use the site manually in Chromium; Ctrl+C or the Dashboard STOP button ends capture.", flush=True)
        print("Only redacted metadata is saved. Do not share the browser profile or CDP port.", flush=True)
        capture.initialize()
        if not capture._session_info:
            print("No page attached yet; open a Chromium tab and navigate to the target site.", flush=True)
        while not writer.stopped:
            if args.duration and time.monotonic() - started >= args.duration:
                break
            if args.stop_file and os.path.exists(args.stop_file):
                break
            if client._reader_error:
                break
            event = client.get_event(timeout=0.5)
            if event is None:
                continue
            capture.handle_event(event)
        succeeded = True
    except KeyboardInterrupt:
        print("Stopping capture…", flush=True)
        succeeded = True
    except Exception as exc:
        print(f"Capture failed ({type(exc).__name__}). Check local Chromium CDP settings; no payload values were printed.", file=sys.stderr, flush=True)
    finally:
        if writer:
            try:
                writer.write({
                    "source": "capture",
                    "kind": "capture_stopped",
                    "stopped_at": utc_now(),
                    "duration_seconds": round(max(0.0, time.monotonic() - started), 2),
                    "reader_state": (client._reader_error or "running") if client else "not_connected",
                })
            finally:
                if client:
                    client.close()
                writer.close()
    if succeeded and run_dir:
        print(f"Sanitized capture saved under: {run_dir}", flush=True)
    return 0 if succeeded else 1


if __name__ == "__main__":
    raise SystemExit(main())
