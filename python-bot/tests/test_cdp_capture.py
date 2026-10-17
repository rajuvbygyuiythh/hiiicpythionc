"""Offline privacy and CDP event tests for the metadata-only capture tool."""
from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import capture


class FakeClient:
    def __init__(self, response_body='{"accessToken":"response-token-private","message":"response body private"}'):
        self.response_body = response_body
        self.calls = []

    def command(self, method, params=None, session_id=None, timeout=None):
        self.calls.append((method, params or {}, session_id))
        if method == "Network.getResponseBody":
            return {"body": self.response_body, "base64Encoded": False}
        if method == "Runtime.evaluate":
            return {"result": {"value": None}}
        if method == "Target.getTargets":
            return {"targetInfos": []}
        return {}


class CDPPrivacyTests(unittest.TestCase):
    def test_domain_matching_is_exact_or_subdomain_only(self):
        self.assertTrue(capture._matches_domain("https://chitchat.gg/", "chitchat.gg"))
        self.assertTrue(capture._matches_domain("wss://api.chitchat.gg/socket", "chitchat.gg"))
        self.assertFalse(capture._matches_domain("https://notchitchat.gg/", "chitchat.gg"))
        self.assertFalse(capture._matches_domain("https://chitchat.gg.example.com/", "chitchat.gg"))
        self.assertFalse(capture._matches_domain("https://example.com/?next=chitchat.gg", "chitchat.gg"))
        self.assertEqual(capture._safe_endpoint("https://api.chitchat.gg/v1", "chitchat.gg")["endpoint_host"], "api.chitchat.gg")
        self.assertEqual(capture._safe_endpoint("https://alice.chitchat.gg/v1", "chitchat.gg")["endpoint_host"], "{subdomain}.chitchat.gg")

    def test_loopback_debugger_url_and_returned_websocket_are_validated(self):
        payload = {"webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/private-id"}

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return json.dumps(payload).encode()

        class Opener:
            def open(self, _request, timeout):
                self.timeout = timeout
                return Response()

        with patch.object(capture, "build_opener", return_value=Opener()):
            result = capture._local_browser_ws_url("http://127.0.0.1:9222")
        self.assertEqual(result, payload["webSocketDebuggerUrl"])

        payload["webSocketDebuggerUrl"] = "ws://192.0.2.55:9222/devtools/browser/private-id"
        with patch.object(capture, "build_opener", return_value=Opener()):
            with self.assertRaisesRegex(ValueError, "non-loopback"):
                capture._local_browser_ws_url("http://127.0.0.1:9222")

        with patch.object(capture, "build_opener") as build_local_opener:
            with self.assertRaisesRegex(ValueError, "localhost/loopback"):
                capture._local_browser_ws_url("http://example.com:9222")
            build_local_opener.assert_not_called()

    def test_cdp_websocket_bypasses_environment_proxies(self):
        class FakeWebSocket:
            def settimeout(self, _timeout):
                pass

            def recv(self):
                return None

            def close(self):
                pass

        class FakeWebSocketModule:
            WebSocketTimeoutException = TimeoutError
            WebSocketConnectionClosedException = ConnectionError

            def __init__(self):
                self.options = None

            def create_connection(self, _url, **options):
                self.options = options
                return FakeWebSocket()

        module = FakeWebSocketModule()
        with patch.dict("sys.modules", {"websocket": module}):
            client = capture.CDPClient("ws://127.0.0.1:9222/devtools/browser/id")
            client.close()
        self.assertEqual(set(module.options["http_no_proxy"]), capture._LOCAL_HOSTS)

    def test_mime_type_metadata_drops_parameters(self):
        self.assertEqual(capture._safe_mime_type("application/json; private=should-not-appear"), "application/json")
        self.assertEqual(capture._safe_mime_type("text/html; charset=utf-8"), "text/html")

    def test_websocket_frame_summary_keeps_schema_not_values(self):
        secret_message = '42["chat_message",{"text":"private chat body","userId":"person-secret-991","authToken":"frame-secret"}]'
        result = capture.summarize_websocket_frame(
            secret_message,
            1,
            "in",
            "wss://api.chitchat.gg/socket.io/?sid=secret-query-value",
            "chitchat.gg",
        )
        serialized = json.dumps(result)
        self.assertEqual(result["kind"], "socket_event")
        self.assertEqual(result["event"], "chat_message")
        self.assertEqual(result["endpoint_host"], "api.chitchat.gg")
        self.assertNotIn("secret-query-value", serialized)
        self.assertNotIn("private chat body", serialized)
        self.assertNotIn("person-secret-991", serialized)
        self.assertNotIn("frame-secret", serialized)

    def test_generic_json_and_binary_frames_are_value_free(self):
        result = capture.summarize_websocket_frame(
            '{"message":"not for the log","accessToken":"never-log-me","items":[7]}',
            1,
            "out",
            {"endpoint_host": "chitchat.gg", "endpoint_path": "/socket", "query_keys": ["token"]},
            "chitchat.gg",
        )
        self.assertEqual(result["kind"], "json_frame")
        serialized = json.dumps(result)
        self.assertNotIn("not for the log", serialized)
        self.assertNotIn("never-log-me", serialized)
        binary = capture.summarize_websocket_frame("QUJDRA==", 2, "in", "wss://chitchat.gg/ws", "chitchat.gg")
        self.assertEqual(binary["kind"], "binary_frame")
        self.assertEqual(binary["frame_bytes"], 4)
        self.assertNotIn("QUJDRA", json.dumps(binary))
        oversized = capture.summarize_websocket_frame(
            '{"data":"' + ('x' * (capture.MAX_FRAME_BYTES + 1)) + '"}',
            1, "in", "wss://chitchat.gg/ws", "chitchat.gg",
        )
        self.assertEqual(oversized["kind"], "oversized_frame")

    def test_http_metadata_trace_never_writes_raw_credentials_or_bodies(self):
        secrets = [
            "query-token-super-secret",
            "bearer-value-super-secret",
            "cookie-value-super-secret",
            "private chat request body",
            "private-user-id-991",
            "response-token-private",
            "response body private",
            "set-cookie-value-super-secret",
        ]
        request_body = json.dumps({
            "message": "private chat request body",
            "userId": "private-user-id-991",
            "refreshToken": "body-token-super-secret",
        })
        secrets.append("body-token-super-secret")

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "capture.jsonl"
            writer = capture.BoundedJsonlWriter(path, 100_000)
            client = FakeClient()
            recorder = capture.CDPMetadataCapture(client, writer, "chitchat.gg")
            recorder._session_info["session-1"] = {"page_id": "p1"}
            recorder.handle_event({
                "method": "Network.requestWillBeSent",
                "sessionId": "session-1",
                "params": {
                    "requestId": "request-1",
                    "timestamp": 10,
                    "type": "XHR",
                    "request": {
                        "url": "https://api.chitchat.gg/api/users/private-user-id-991/messages?token=query-token-super-secret",
                        "method": "POST",
                        "headers": {
                            "Authorization": "Bearer bearer-value-super-secret",
                            "Cookie": "sid=cookie-value-super-secret",
                            "Content-Type": "application/json; charset=utf-8",
                        },
                        "postData": request_body,
                    },
                },
            })
            recorder.handle_event({
                "method": "Network.responseReceived",
                "sessionId": "session-1",
                "params": {
                    "requestId": "request-1",
                    "timestamp": 10.2,
                    "type": "XHR",
                    "response": {
                        "url": "https://api.chitchat.gg/api/users/private-user-id-991/messages?token=query-token-super-secret",
                        "status": 200,
                        "protocol": "h2",
                        "mimeType": "application/json",
                        "headers": {
                            "Content-Type": "application/json; charset=utf-8",
                            "Content-Length": "120",
                            "Set-Cookie": "sid=set-cookie-value-super-secret",
                        },
                    },
                },
            })
            recorder.handle_event({
                "method": "Network.loadingFinished",
                "sessionId": "session-1",
                "params": {"requestId": "request-1", "timestamp": 10.3},
            })
            recorder.handle_event({
                "method": "Network.requestWillBeSent",
                "sessionId": "session-1",
                "params": {
                    "requestId": "unknown-length-1", "timestamp": 10.4, "type": "XHR",
                    "request": {"url": "https://api.chitchat.gg/api/v1/unknown-length", "method": "GET", "headers": {}},
                },
            })
            recorder.handle_event({
                "method": "Network.responseReceived",
                "sessionId": "session-1",
                "params": {
                    "requestId": "unknown-length-1", "timestamp": 10.5, "type": "XHR",
                    "response": {
                        "url": "https://api.chitchat.gg/api/v1/unknown-length",
                        "status": 200, "mimeType": "application/json",
                        "headers": {"Content-Type": "application/json"},
                    },
                },
            })
            recorder.handle_event({
                "method": "Network.loadingFinished",
                "sessionId": "session-1",
                "params": {"requestId": "unknown-length-1", "timestamp": 10.6},
            })

            content = path.read_text(encoding="utf-8")
            records = [json.loads(line) for line in content.splitlines()]
            for secret in secrets:
                self.assertNotIn(secret, content)
            self.assertTrue(any(record.get("kind") == "api_request" for record in records))
            response_shape = next(record for record in records if record.get("kind") == "response_body_shape")
            self.assertEqual(response_shape["body_shape"]["type"], "json")
            self.assertTrue(response_shape["sensitive_body_field_names"])
            self.assertNotIn("url", next(iter(recorder._request_map.values())))
            self.assertNotIn("query-token-super-secret", json.dumps(list(recorder._request_map.values())))
            self.assertIn("authorization", content.lower())
            self.assertIn("cookie", content.lower())
            self.assertIn("{id}", content)

            # A redirect/response to another host must not inherit the target
            # site's endpoint label or cause a third-party body fetch.
            count_before = len(records)
            recorder.handle_event({
                "method": "Network.requestWillBeSent",
                "sessionId": "session-1",
                "params": {
                    "requestId": "redirect-1", "timestamp": 11, "type": "XHR",
                    "request": {"url": "https://api.chitchat.gg/api/me", "method": "GET", "headers": {}},
                },
            })
            recorder.handle_event({
                "method": "Network.requestWillBeSent",
                "sessionId": "session-1",
                "params": {
                    "requestId": "redirect-1", "timestamp": 11.1, "type": "XHR",
                    "request": {"url": "https://third-party.example/private", "method": "GET", "headers": {}},
                },
            })
            recorder.handle_event({
                "method": "Network.responseReceived",
                "sessionId": "session-1",
                "params": {
                    "requestId": "redirect-1", "timestamp": 11.2, "type": "XHR",
                    "response": {"url": "https://third-party.example/private", "status": 200, "headers": {"Content-Type": "application/json"}},
                },
            })
            self.assertEqual(len(recorder._request_map), 2)
            self.assertEqual(len(client.calls), 2)  # only target-site bodies were fetched
            self.assertEqual(count_before, len(records))
            writer.close()

    def test_websocket_handshake_and_frames_preserve_type_but_not_values(self):
        secrets = [
            "private-ws-query-value",
            "websocket-bearer-private",
            "websocket-cookie-private",
            "the complete private message",
            "chat-user-private-001",
            "websocket-token-private",
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "capture.jsonl"
            writer = capture.BoundedJsonlWriter(path, 100_000)
            recorder = capture.CDPMetadataCapture(FakeClient(), writer, "chitchat.gg")
            recorder._session_info["session-1"] = {"page_id": "p1"}
            recorder.handle_event({
                "method": "Network.requestWillBeSent",
                "sessionId": "session-1",
                "params": {
                    "requestId": "ws-request-1",
                    "timestamp": 20,
                    "type": "WebSocket",
                    "request": {
                        "url": "wss://socket.chitchat.gg/socket.io/?EIO=4&sid=private-ws-query-value",
                        "method": "GET",
                        "headers": {
                            "Authorization": "Bearer websocket-bearer-private",
                            "Cookie": "sid=websocket-cookie-private",
                        },
                    },
                },
            })
            recorder.handle_event({
                "method": "Network.webSocketCreated",
                "sessionId": "session-1",
                "params": {
                    "requestId": "ws-request-1",
                    "url": "wss://socket.chitchat.gg/socket.io/?EIO=4&sid=private-ws-query-value",
                },
            })
            recorder.handle_event({
                "method": "Network.webSocketWillSendHandshakeRequest",
                "sessionId": "session-1",
                "params": {
                    "requestId": "ws-request-1",
                    "request": {"headers": {"Authorization": "websocket-bearer-private"}},
                },
            })
            recorder.handle_event({
                "method": "Network.webSocketHandshakeResponseReceived",
                "sessionId": "session-1",
                "params": {
                    "requestId": "ws-request-1",
                    "response": {"status": 101, "headers": {"Set-Cookie": "websocket-cookie-private"}},
                },
            })
            recorder.handle_event({
                "method": "Network.webSocketFrameReceived",
                "sessionId": "session-1",
                "params": {
                    "requestId": "ws-request-1",
                    "response": {
                        "opcode": 1,
                        "payloadData": '42["chat_message",{"text":"the complete private message","userId":"chat-user-private-001","authToken":"websocket-token-private"}]',
                    },
                },
            })
            writer.close()

            content = path.read_text(encoding="utf-8")
            records = [json.loads(line) for line in content.splitlines()]
            for secret in secrets:
                self.assertNotIn(secret, content)
            frame = next(record for record in records if record.get("kind") == "websocket_frame")
            self.assertEqual(frame["frame_kind"], "socket_event")
            self.assertEqual(frame["event"], "chat_message")
            handshake = next(record for record in records if record.get("kind") == "websocket_handshake_request")
            self.assertEqual(handshake["header_values"], "redacted")
            self.assertEqual(handshake["header_order"], "not_recorded")
            self.assertIn("sid", json.dumps(records))
            self.assertNotIn("url", next(iter(recorder._request_map.values())))
            self.assertNotIn("url", next(iter(recorder._websocket_map.values())))

    def test_storage_summaries_keep_only_names_and_size_buckets(self):
        storage = capture.CDPMetadataCapture._sanitize_storage({
            "count": 3,
            "items": [
                {"key": "accessToken", "present": True, "size": "33-256"},
                {"key": "person@example.com", "present": True, "size": "1-32"},
                {"key": "9876543210123456", "present": True, "size": "empty"},
            ],
        })
        serialized = json.dumps(storage)
        self.assertIn("accessToken", serialized)
        self.assertIn("sensitive_key_name", serialized)
        self.assertNotIn("person@example.com", serialized)
        self.assertNotIn("9876543210123456", serialized)
        self.assertNotIn("value", serialized)

    def test_storage_snapshot_masks_dynamic_subdomain(self):
        class SnapshotClient(FakeClient):
            def command(self, method, params=None, session_id=None, timeout=None):
                self.calls.append((method, params or {}, session_id))
                if method == "Runtime.evaluate":
                    return {"result": {"value": {
                        "origin": "https://alice.chitchat.gg",
                        "localStorage": {"count": 0, "items": []},
                        "sessionStorage": {"count": 0, "items": []},
                        "visibleCookieNames": [],
                        "indexedDBDatabases": [],
                    }}}
                return {}

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "capture.jsonl"
            writer = capture.BoundedJsonlWriter(path, 10_000)
            recorder = capture.CDPMetadataCapture(SnapshotClient(), writer, "chitchat.gg")
            recorder._session_info["session-1"] = {"page_id": "p1", "endpoint": {"endpoint_host": "{subdomain}.chitchat.gg"}}
            recorder._capture_storage_snapshot("session-1", "p1")
            writer.close()
            content = path.read_text(encoding="utf-8")
            records = [json.loads(line) for line in content.splitlines()]
        snapshot = next(record for record in records if record.get("kind") == "storage_snapshot")
        self.assertEqual(snapshot["origin_host"], "{subdomain}.chitchat.gg")
        self.assertNotIn("alice", content)

    def test_writer_enforces_size_cap_and_private_file_mode(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "capture.jsonl"
            writer = capture.BoundedJsonlWriter(path, 4096)
            self.assertTrue(writer.write({"kind": "small_record"}))
            self.assertFalse(writer.write({"kind": "large_record", "payload": "x" * 5000}))
            self.assertTrue(writer.stopped)
            writer.close()
            content = path.read_text(encoding="utf-8")
            self.assertIn("size_limit_reached", content)
            self.assertLessEqual(path.stat().st_size, 4096)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_event_queue_and_tracking_maps_are_bounded(self):
        self.assertGreater(capture.MAX_QUEUED_CDP_EVENTS, 0)
        self.assertGreater(capture.MAX_TRACKED_REQUESTS, 0)
        self.assertGreater(capture.MAX_TRACKED_WEBSOCKETS, 0)
        self.assertGreater(capture.MAX_HTTP_BODY_BYTES, 0)

    def test_non_target_pages_are_not_inspected_for_storage(self):
        client = FakeClient()
        with tempfile.TemporaryDirectory() as temp_dir:
            writer = capture.BoundedJsonlWriter(Path(temp_dir) / "capture.jsonl", 10_000)
            recorder = capture.CDPMetadataCapture(client, writer, "chitchat.gg")
            recorder._register_target("session-1", {
                "targetId": "target-1", "type": "page", "url": "https://example.com/"
            })
            writer.close()
        methods = [call[0] for call in client.calls]
        self.assertIn("Page.enable", methods)
        self.assertIn("Network.enable", methods)
        self.assertNotIn("Runtime.enable", methods)
        self.assertNotIn("DOMStorage.enable", methods)
        self.assertNotIn("Runtime.evaluate", methods)


if __name__ == "__main__":
    unittest.main(verbosity=2)
