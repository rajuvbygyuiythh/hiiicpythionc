"""Opt-in, privacy-preserving browser API and WebSocket tracing.

The trace records protocol direction, event names, route labels, status codes,
and bounded JSON/form structure. It never persists raw message/body values,
header values, cookies, tokens, or URL query values; header names only may appear.
"""

from __future__ import annotations

import json
import os
import re
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

MAX_TRACE_BYTES = 1_000_000
MAX_HTTP_BODY_BYTES = 256_000
TARGET_DOMAIN = "chitchat.gg"
MAX_FRAME_BYTES = 256_000
MAX_SHAPE_NODES = 40
MAX_SHAPE_DEPTH = 4
MAX_OBJECT_KEYS = 40
_TRACE_FILE_LOCK = threading.RLock()
_INITIALIZED_DEFAULT_PATHS = set()

_DYNAMIC_PATH_PARENTS = {
    "user", "users", "match", "matches", "chat", "chats", "room", "rooms",
    "conversation", "conversations", "session", "sessions", "friend", "friends",
    "profile", "profiles", "message", "messages", "account", "accounts",
    "participant", "participants", "member", "members", "u", "id",
}
_DYNAMIC_MAP_PARENTS = {
    "user", "users", "usersbyid", "byuserid", "profiles", "profilesbyid",
    "friends", "members", "participants", "sessions", "matches", "chats",
    "rooms", "conversations",
}
_STATIC_PATH_ACTIONS = {
    "new", "create", "start", "stop", "skip", "next", "leave", "join", "send",
    "status", "me", "list", "search", "active", "socket.io", "health", "api",
}
_ID_PATH_RE = re.compile(
    r"^(?:[0-9]+|[0-9a-f]{16,}|[0-9a-f]{8}-[0-9a-f-]{27,}|[^/]{48,})$",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"^[^/@]+@[^/@]+\.[^/@]+$")

_KEY_RE = re.compile(r"[^A-Za-z0-9_$.-]+")
_EVENT_RE = re.compile(r"[^A-Za-z0-9_$.-]+")
_NAMESPACE_RE = re.compile(r"[^A-Za-z0-9_/$.-]+")


def socket_trace_enabled(environ=None) -> bool:
    """Return whether the user explicitly enabled the metadata-only trace."""
    values = os.environ if environ is None else environ
    return str(values.get("EVA_SOCKET_TRACE", "")).strip().lower() in {
        "1", "true", "yes", "on"
    }


def _label(value, pattern, limit=80):
    text = str(value or "")
    text = pattern.sub("_", text).strip("_")
    return text[:limit]


def _safe_path(web_url):
    """Keep useful route names while masking likely IDs, usernames and tokens."""
    try:
        raw_path = urlsplit(str(web_url or "")).path or "/"
    except (TypeError, ValueError):
        return "/"
    safe_segments = []
    previous = ""
    for raw_segment in raw_path.split("/")[:40]:
        if not raw_segment:
            safe_segments.append("")
            previous = ""
            continue
        segment = unquote(raw_segment[:160])[:160]
        lowered = segment.lower()
        if (
            _ID_PATH_RE.fullmatch(segment)
            or _EMAIL_RE.fullmatch(segment)
            or (previous in _DYNAMIC_PATH_PARENTS and lowered not in _STATIC_PATH_ACTIONS)
        ):
            safe_segments.append("{id}")
        else:
            safe_segments.append(_label(segment, _KEY_RE, 80))
        previous = lowered
    result = "/".join(safe_segments)
    return result[:500] or "/"


def _url_metadata(web_url):
    """Return a safe endpoint label; never retain credentials or query values."""
    try:
        parsed = urlsplit(str(web_url or ""))
        host = (parsed.hostname or "")[:200]
        try:
            query_keys = sorted(
                {
                    _label(key, _KEY_RE, 64)
                    for key, _value in parse_qsl(
                        parsed.query, keep_blank_values=True, max_num_fields=100
                    )[:100]
                    if key
                }
            )[:40]
        except (ValueError, TypeError):
            query_keys = []
        return {"endpoint_host": host, "endpoint_path": _safe_path(web_url), "query_keys": query_keys}
    except (TypeError, ValueError):
        return {"endpoint_host": "", "endpoint_path": "/", "query_keys": []}


def _is_target_url(web_url):
    """Limit capture to Chitchat hosts; never record unrelated browsing traffic."""
    try:
        host = (urlsplit(str(web_url or "")).hostname or "").lower().rstrip(".")
    except (TypeError, ValueError):
        return False
    return host == TARGET_DOMAIN or host.endswith("." + TARGET_DOMAIN)


def _body_shape(body_text, content_type=""):
    """Summarize JSON/form bodies without retaining scalar values."""
    if body_text is None or body_text == "":
        return {"type": "empty"}
    if isinstance(body_text, bytes):
        byte_length = len(body_text)
        try:
            text = body_text.decode("utf-8")
        except UnicodeDecodeError:
            return {"type": "binary", "bytes": byte_length}
    else:
        text = str(body_text)
        byte_length = len(text.encode("utf-8", errors="replace"))
    if byte_length > MAX_HTTP_BODY_BYTES:
        return {"type": "omitted_large", "bytes": byte_length}

    mime_type = str(content_type or "").split(";", 1)[0].strip().lower()
    if "json" in mime_type or text.lstrip().startswith(("{", "[")):
        try:
            value = json.loads(text)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {"type": "invalid_json", "bytes": byte_length}
        shape = []
        _append_shape(value, "body", shape)
        return {"type": "json", "shape": shape}

    if mime_type == "application/x-www-form-urlencoded":
        try:
            fields = parse_qsl(text, keep_blank_values=True, max_num_fields=200)
        except (ValueError, TypeError):
            fields = []
        return {
            "type": "form",
            "field_count": len(fields),
            "keys": sorted({_shape_key(key) for key, _value in fields if key})[:40],
        }
    return {"type": "non_json", "bytes": byte_length}


def _shape_key(value, dynamic_map_key=False):
    """Keep schema labels, but never persist likely ID/email dictionary keys."""
    text = str(value or "")
    if dynamic_map_key or _ID_PATH_RE.fullmatch(text) or _EMAIL_RE.fullmatch(text):
        return "{key}"
    return _label(text, _KEY_RE, 64)


def _value_type(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, list):
        return "array"
    return "other"


def _append_shape(value, path, output, depth=0):
    """Append bounded JSON structure without copying any scalar values."""
    if len(output) >= MAX_SHAPE_NODES:
        return

    if isinstance(value, dict):
        entries = list(value.items())
        parent_key = path.rsplit(".", 1)[-1].split("[", 1)[0].lower()
        dynamic_map = parent_key in _DYNAMIC_MAP_PARENTS or parent_key.endswith("byid")
        keys = [_shape_key(key, dynamic_map) for key, _ in entries[:MAX_OBJECT_KEYS]]
        output.append({"path": path, "type": "object", "keys": keys})
        if depth >= MAX_SHAPE_DEPTH:
            return
        for key, child in entries[:MAX_OBJECT_KEYS]:
            child_path = f"{path}.{_shape_key(key, dynamic_map)}"
            if isinstance(child, (dict, list)):
                _append_shape(child, child_path, output, depth + 1)
            else:
                output.append({"path": child_path, "type": _value_type(child)})
            if len(output) >= MAX_SHAPE_NODES:
                return
        return

    if isinstance(value, list):
        output.append({"path": path, "type": "array", "length": len(value)})
        if depth >= MAX_SHAPE_DEPTH:
            return
        for index, child in enumerate(value[:4]):
            child_path = f"{path}[{index}]"
            if isinstance(child, (dict, list)):
                _append_shape(child, child_path, output, depth + 1)
            else:
                output.append({"path": child_path, "type": _value_type(child)})
            if len(output) >= MAX_SHAPE_NODES:
                return
        return

    output.append({"path": path, "type": _value_type(value)})


def _parse_json_shape(text, path):
    if not text:
        return None, [], False
    try:
        value = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None, [], True
    shapes = []
    _append_shape(value, path, shapes)
    return value, shapes, False


def _split_namespace_and_ack(body):
    namespace = "/"
    if body.startswith("/"):
        comma = body.find(",")
        if comma >= 0:
            namespace = _label(body[:comma], _NAMESPACE_RE, 100) or "/"
            body = body[comma + 1:]
        else:
            namespace, body = _label(body, _NAMESPACE_RE, 100) or "/", ""

    ack_match = re.match(r"^\d+", body)
    has_ack_id = ack_match is not None
    if ack_match:
        body = body[ack_match.end():]
    return namespace, has_ack_id, body


def summarize_frame(frame, direction, websocket_url=""):
    """Summarize an Engine.IO/Socket.IO frame without retaining its values."""
    direction = direction if direction in {"in", "out"} else "unknown"
    endpoint = _url_metadata(websocket_url)
    if isinstance(frame, bytes):
        return {
            "direction": direction,
            **endpoint,
            "frame_bytes": len(frame),
            "kind": "binary_frame",
        }
    if not isinstance(frame, str):
        return {
            "direction": direction,
            **endpoint,
            "frame_bytes": 0,
            "kind": "unsupported_frame_type",
            "frame_type": _value_type(frame),
        }

    frame_bytes = len(frame.encode("utf-8", errors="replace"))
    result = {
        "direction": direction,
        **endpoint,
        "frame_bytes": frame_bytes,
    }
    if not frame:
        result["kind"] = "empty_frame"
        return result
    if frame_bytes > MAX_FRAME_BYTES:
        result["kind"] = "oversized_frame"
        return result

    # Engine.IO packet types: 0=open, 1=close, 2=ping, 3=pong, 4=message,
    # 5=upgrade, 6=noop. Socket.IO packet types are nested inside type 4.
    engine_type = frame[0]
    if engine_type == "0":
        result["kind"] = "engine_open"
        _, shape, invalid = _parse_json_shape(frame[1:], "handshake")
        if shape:
            result["data_shape"] = shape
        if invalid:
            result["decode_error"] = True
        return result
    if engine_type in {"1", "2", "3", "5", "6"}:
        result["kind"] = {
            "1": "engine_close",
            "2": "engine_ping",
            "3": "engine_pong",
            "5": "engine_upgrade",
            "6": "engine_noop",
        }[engine_type]
        return result
    if engine_type != "4":
        result["kind"] = "unknown_engine_packet"
        result["engine_packet_type"] = engine_type
        return result

    if len(frame) < 2:
        result["kind"] = "engine_message"
        return result

    socket_type = frame[1]
    body = frame[2:]
    packet_names = {
        "0": "socket_connect",
        "1": "socket_disconnect",
        "2": "socket_event",
        "3": "socket_ack",
        "4": "socket_connect_error",
        "5": "socket_binary_event",
        "6": "socket_binary_ack",
    }
    result["kind"] = packet_names.get(socket_type, "socket_packet")
    namespace, has_ack_id, body = _split_namespace_and_ack(body)
    result["namespace"] = namespace
    if has_ack_id:
        result["has_ack_id"] = True

    if socket_type == "1":
        return result

    decoded, shape, invalid = _parse_json_shape(body, "payload")
    if shape:
        result["data_shape"] = shape
    if invalid:
        result["decode_error"] = True

    if socket_type == "2" and isinstance(decoded, list) and decoded:
        if isinstance(decoded[0], str):
            result["event"] = _label(decoded[0], _EVENT_RE, 80) or "other"
            result.pop("data_shape", None)
            payload_shapes = []
            for index, value in enumerate(decoded[1:5]):
                _append_shape(value, f"args[{index}]", payload_shapes)
                if len(payload_shapes) >= MAX_SHAPE_NODES:
                    break
            if payload_shapes:
                result["data_shape"] = payload_shapes
    return result


class SocketTraceRecorder:
    """Write a bounded, value-redacted browser API/WebSocket trace.

    By default all workers append to ``capture/debug-api.txt``. The combined
    file and source-specific WebSocket/API JSONL sidecars are reset once when
    tracing first starts in a process. Set ``EVA_SOCKET_TRACE_FILE`` to choose
    another combined-file path. HTTP header names may be summarized, but header
    values, cookies, tokens, URL query values, and raw bodies/frames are never written.
    """

    def __init__(self, thread_id=0, path=None, max_bytes=MAX_TRACE_BYTES):
        root = Path(__file__).resolve().parent.parent
        is_default_path = path is None
        if is_default_path:
            configured_path = os.environ.get("EVA_SOCKET_TRACE_FILE", "").strip()
            path = Path(configured_path) if configured_path else root / "capture" / "debug-api.txt"
            if not path.is_absolute():
                path = root / path
        self.path = Path(path)
        self.thread_id = thread_id
        self.max_bytes = max(256, int(max_bytes))
        self._lock = threading.RLock()
        self._request_counter = 0
        self._request_ids = {}
        self._request_started = {}
        self._stopped = False
        self._sidecar_paths = {}
        if is_default_path:
            self._sidecar_paths = {
                "websocket_frame": self.path.parent / "websocket.jsonl",
                "websocket_handshake": self.path.parent / "websocket.jsonl",
                "http_request": self.path.parent / "http-api.jsonl",
                "http_response": self.path.parent / "http-api.jsonl",
            }
            self._initialize_default_file()
        try:
            self._written_bytes = self.path.stat().st_size
        except OSError:
            self._written_bytes = 0
        self._stopped = self._written_bytes >= self.max_bytes

    def _initialize_default_file(self):
        """Truncate the shared default trace once per path and process."""
        try:
            key = str(self.path.resolve())
        except OSError:
            key = str(self.path.absolute())
        with _TRACE_FILE_LOCK:
            if key in _INITIALIZED_DEFAULT_PATHS:
                return
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                start = {
                    "source": "trace",
                    "kind": "capture_started",
                    "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                    "privacy": "metadata_only",
                }
                encoded = (json.dumps(start, separators=(",", ":")) + "\n").encode("utf-8")
                outputs = {self.path, *self._sidecar_paths.values()}
                for output_path in outputs:
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    with output_path.open("wb") as handle:
                        handle.write(encoded)
                        handle.flush()
                _INITIALIZED_DEFAULT_PATHS.add(key)
            except OSError:
                # Recording will retry on the first event and the caller logs
                # the path or failure through the existing automation logger.
                return

    def attach_page(self, page):
        """Observe WebSockets plus fetch/XHR API request-response metadata."""
        page.on("websocket", self.attach_websocket)
        page.on("request", self._on_request)
        page.on("response", self._on_response)
        page.on("requestfailed", self._on_request_failed)
        page.on("framenavigated", self._on_frame_navigated)

    def attach_websocket(self, websocket):
        url = getattr(websocket, "url", "")
        if not _is_target_url(url):
            return
        websocket.on("framesent", lambda frame: self.record(frame, "out", url))
        websocket.on("framereceived", lambda frame: self.record(frame, "in", url))
        websocket.on("close", lambda *_args: self._record_websocket_state("websocket_closed", url))
        websocket.on("socketerror", lambda *_args: self._record_websocket_state("websocket_error", url))

    def _record_websocket_state(self, kind, websocket_url):
        summary = {
            "source": "websocket_frame",
            "kind": kind,
            "direction": "unknown",
            **_url_metadata(websocket_url),
            "worker_id": self.thread_id,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        }
        return self._write_summary(summary)

    def record(self, frame, direction, websocket_url=""):
        summary = summarize_frame(frame, direction, websocket_url)
        summary["source"] = "websocket_frame"
        summary["worker_id"] = self.thread_id
        summary["timestamp"] = datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        return self._write_summary(summary)

    @staticmethod
    def _headers(obj):
        try:
            headers = obj.headers
            return headers if isinstance(headers, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _content_type(headers):
        value = next(
            (value for key, value in headers.items() if str(key).lower() == "content-type"),
            "",
        )
        # Drop multipart boundaries and other parameters; they are irrelevant
        # to schema inspection and should not end up in a shareable trace.
        return str(value or "").split(";", 1)[0].strip().lower()[:100]

    @staticmethod
    def _safe_header_names(headers):
        """List header NAMES only; values (especially auth/cookie) stay private."""
        return sorted({_label(key, _KEY_RE, 100).lower() for key in headers if key})[:40]

    @staticmethod
    def _credential_header_names(headers):
        """List auth-related header NAMES only; never retain header values."""
        sensitive_markers = ("auth", "token", "cookie", "session", "api-key", "apikey", "credential")
        names = {
            _label(key, _KEY_RE, 100).lower()
            for key in headers
            if any(marker in str(key).lower() for marker in sensitive_markers)
        }
        return sorted(names)[:20]

    def _next_request_id(self, request):
        key = id(request)
        with self._lock:
            existing = self._request_ids.get(key)
            if existing:
                return existing
            self._request_counter += 1
            request_id = f"{self.thread_id}-{self._request_counter}"
            self._request_ids[key] = request_id
            if len(self._request_ids) > 2048:
                oldest = next(iter(self._request_ids))
                self._request_ids.pop(oldest, None)
                self._request_started.pop(oldest, None)
            return request_id

    def _take_request_meta(self, request):
        key = id(request)
        with self._lock:
            request_id = self._request_ids.pop(key, None)
            if request_id is None:
                self._request_counter += 1
                request_id = f"{self.thread_id}-{self._request_counter}"
            started = self._request_started.pop(key, None)
        elapsed_ms = None if started is None else round(max(0.0, time.perf_counter() - started) * 1000, 2)
        return request_id, elapsed_ms

    @staticmethod
    def _is_api_request(request):
        try:
            return (
                str(request.resource_type or "").lower() in {"fetch", "xhr"}
                and _is_target_url(request.url)
            )
        except Exception:
            return False

    def _on_request(self, request):
        try:
            resource_type = str(request.resource_type or "").lower()
            url = str(request.url)
        except Exception:
            return
        is_api = resource_type in {"fetch", "xhr"}
        is_websocket = resource_type == "websocket"
        if (not is_api and not is_websocket) or not _is_target_url(url):
            return
        try:
            method = str(request.method or "GET").upper()[:16]
            headers = self._headers(request)
            header_names = self._safe_header_names(headers)
            content_type = self._content_type(headers)
            credential_header_names = self._credential_header_names(headers)
            post_data = request.post_data if is_api else None
        except Exception:
            url, method, content_type, post_data = "", "GET", "", None
            header_names = []
            credential_header_names = []
        request_id = self._next_request_id(request) if is_api else None
        if is_api:
            with self._lock:
                self._request_started[id(request)] = time.perf_counter()
        summary = {
            "source": "http_request" if is_api else "websocket_handshake",
            "kind": "api_request" if is_api else "websocket_handshake",
            "worker_id": self.thread_id,
            "request_id": request_id,
            "method": method,
            "resource_type": resource_type,
            **_url_metadata(url),
            "header_names": header_names,
            "credential_header_names": credential_header_names,
            "content_type": content_type,
            "body_shape": _body_shape(post_data, content_type) if is_api else {"type": "not_applicable"},
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        }
        self._write_summary(summary)

    def _on_response(self, response):
        try:
            request = response.request
        except Exception:
            return
        if not self._is_api_request(request):
            return
        request_id, elapsed_ms = self._take_request_meta(request)
        try:
            url = str(request.url)
            method = str(request.method or "GET").upper()[:16]
            resource_type = str(request.resource_type or "")[:16]
            status = int(response.status)
            headers = self._headers(response)
            header_names = self._safe_header_names(headers)
            content_type = self._content_type(headers)
            credential_header_names = self._credential_header_names(headers)
        except Exception:
            url, method, resource_type, status, content_type = "", "GET", "", 0, ""
            headers = {}
            header_names = []
            credential_header_names = []

        body_summary = {"type": "not_json"}
        if "json" in content_type:
            content_length = next(
                (value for key, value in headers.items() if str(key).lower() == "content-length"),
                "",
            )
            try:
                if content_length and int(content_length) > MAX_HTTP_BODY_BYTES:
                    body_summary = {"type": "omitted_large", "bytes": int(content_length)}
                else:
                    body_summary = _body_shape(response.body(), content_type)
            except Exception:
                body_summary = {"type": "unavailable"}

        summary = {
            "source": "http_response",
            "kind": "api_response",
            "worker_id": self.thread_id,
            "request_id": request_id,
            "method": method,
            "resource_type": resource_type,
            **_url_metadata(url),
            "status": status,
            "elapsed_ms": elapsed_ms,
            "header_names": header_names,
            "credential_header_names": credential_header_names,
            "content_type": content_type,
            "body_shape": body_summary,
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        }
        self._write_summary(summary)

    def _on_request_failed(self, request):
        if not self._is_api_request(request):
            return
        try:
            url = str(request.url)
            method = str(request.method or "GET").upper()[:16]
            resource_type = str(request.resource_type or "")[:16]
        except Exception:
            url, method, resource_type = "", "GET", ""
        request_id, elapsed_ms = self._take_request_meta(request)
        summary = {
            "source": "http_request",
            "kind": "api_request_failed",
            "worker_id": self.thread_id,
            "request_id": request_id,
            "elapsed_ms": elapsed_ms,
            "method": method,
            "resource_type": resource_type,
            **_url_metadata(url),
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        }
        self._write_summary(summary)

    def _on_frame_navigated(self, frame):
        try:
            if frame != frame.page.main_frame:
                return
            url = str(frame.url or "")
            if not _is_target_url(url):
                return
        except Exception:
            return
        summary = {
            "source": "page",
            "kind": "main_frame_navigation",
            "worker_id": self.thread_id,
            **_url_metadata(url),
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
        }
        self._write_summary(summary)

    def _write_summary(self, summary):
        summary.setdefault("worker_id", self.thread_id)
        summary.setdefault(
            "timestamp", datetime.now(timezone.utc).isoformat(timespec="milliseconds")
        )
        line = (json.dumps(summary, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        marker = {
            "source": "trace",
            "kind": "trace_limit_reached",
            "worker_id": self.thread_id,
            "timestamp": summary["timestamp"],
            "max_bytes": self.max_bytes,
        }
        marker_line = (json.dumps(marker, separators=(",", ":")) + "\n").encode("utf-8")

        with self._lock:
            if self._stopped:
                return False
            with _TRACE_FILE_LOCK:
                try:
                    current_bytes = self.path.stat().st_size
                except OSError:
                    current_bytes = 0
                try:
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    if current_bytes + len(line) + len(marker_line) > self.max_bytes:
                        if current_bytes + len(marker_line) <= self.max_bytes:
                            with self.path.open("ab") as handle:
                                handle.write(marker_line)
                                handle.flush()
                            self._written_bytes = current_bytes + len(marker_line)
                        self._stopped = True
                        return False
                    with self.path.open("ab") as handle:
                        handle.write(line)
                        handle.flush()
                    self._written_bytes = current_bytes + len(line)

                    sidecar = self._sidecar_paths.get(summary.get("source"))
                    if sidecar is not None:
                        sidecar_marker = {
                            **marker,
                            "file": sidecar.name,
                        }
                        sidecar_marker_line = (
                            json.dumps(sidecar_marker, separators=(",", ":")) + "\n"
                        ).encode("utf-8")
                        try:
                            sidecar.parent.mkdir(parents=True, exist_ok=True)
                            try:
                                sidecar_bytes = sidecar.stat().st_size
                            except OSError:
                                sidecar_bytes = 0
                            if sidecar_bytes + len(line) + len(sidecar_marker_line) <= self.max_bytes:
                                with sidecar.open("ab") as handle:
                                    handle.write(line)
                                    handle.flush()
                            elif sidecar_bytes + len(sidecar_marker_line) <= self.max_bytes:
                                with sidecar.open("ab") as handle:
                                    handle.write(sidecar_marker_line)
                                    handle.flush()
                        except OSError:
                            # The combined timeline remains the authoritative
                            # copy if a sidecar cannot be written.
                            pass
                    return True
                except OSError:
                    self._stopped = True
                    return False
