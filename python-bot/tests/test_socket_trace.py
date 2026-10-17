"""Offline tests for the opt-in metadata-only Socket.IO trace."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from browser.socket_trace import (
    SocketTraceRecorder,
    socket_trace_enabled,
    summarize_frame,
)


class SocketTraceTests(unittest.TestCase):
    def test_enable_flag_requires_an_explicit_truthy_value(self):
        self.assertFalse(socket_trace_enabled({}))
        self.assertFalse(socket_trace_enabled({"EVA_SOCKET_TRACE": "0"}))
        self.assertTrue(socket_trace_enabled({"EVA_SOCKET_TRACE": "yes"}))

    def test_socket_connect_records_auth_field_names_not_values_or_url_query(self):
        summary = summarize_frame(
            '40{"release":"private-release","token":"private-token"}',
            "out",
            "wss://user:pass@api.chitchat.gg/socket.io/?sid=private-sid",
        )
        serialized = json.dumps(summary)

        self.assertEqual(summary["kind"], "socket_connect")
        self.assertEqual(summary["endpoint_host"], "api.chitchat.gg")
        self.assertIn("release", serialized)
        self.assertIn("token", serialized)
        for secret in ("private-release", "private-token", "private-sid", "user:pass"):
            self.assertNotIn(secret, serialized)

    def test_event_records_nested_payload_shape_but_not_chat_values(self):
        summary = summarize_frame(
            '42["chatMessage",{"message":{"conversationId":"conv-private",'
            '"content":"private message body","author":{"id":"user-private"}}}]',
            "out",
            "wss://api.chitchat.gg/socket.io/?EIO=4&sid=private-sid",
        )
        serialized = json.dumps(summary)
        shape_paths = {item["path"] for item in summary["data_shape"]}

        self.assertEqual(summary["event"], "chatMessage")
        self.assertEqual(summary["direction"], "out")
        self.assertIn("args[0].message", shape_paths)
        self.assertIn("args[0].message.author", shape_paths)
        self.assertIn("conversationId", serialized)
        self.assertIn("content", serialized)
        self.assertIn(
            {"path": "args[0].message.content", "type": "string"},
            summary["data_shape"],
        )
        for secret in ("conv-private", "private message body", "user-private", "private-sid"):
            self.assertNotIn(secret, serialized)

    def test_user_map_keys_are_masked_from_schema_metadata(self):
        summary = summarize_frame(
            '42["userList",{"users":{"alice@example.test":{"uid":"1234567890123456"}}}]',
            "in",
        )
        serialized = json.dumps(summary)

        self.assertIn("args[0].users.{key}", {item["path"] for item in summary["data_shape"]})
        self.assertNotIn("alice@example.test", serialized)
        self.assertNotIn("1234567890123456", serialized)

    def test_namespace_and_ack_id_are_summarized_without_ack_value(self):
        summary = summarize_frame('42/admin,123["action",{"ok":true}]', "out")

        self.assertEqual(summary["namespace"], "/admin")
        self.assertTrue(summary["has_ack_id"])
        self.assertEqual(summary["event"], "action")
        self.assertNotIn("123", json.dumps(summary))

    def test_engine_open_and_heartbeat_values_are_not_recorded(self):
        opened = summarize_frame(
            '0{"sid":"private-sid","pid":"private-pid","pingInterval":25000}',
            "in",
        )
        ping = summarize_frame("2", "in")
        pong = summarize_frame("3", "out")

        self.assertEqual(opened["kind"], "engine_open")
        self.assertEqual(ping["kind"], "engine_ping")
        self.assertEqual(pong["kind"], "engine_pong")
        self.assertNotIn("private-sid", json.dumps(opened))
        self.assertNotIn("private-pid", json.dumps(opened))

    def test_malformed_and_binary_frames_never_include_raw_content(self):
        malformed = summarize_frame('42["chatMessage",not-json-secret]', "out")
        binary = summarize_frame(b"binary-private-data", "in")
        oversized = summarize_frame("4" + "x" * 300_000, "in")

        self.assertTrue(malformed["decode_error"])
        self.assertNotIn("not-json-secret", json.dumps(malformed))
        self.assertEqual(binary["kind"], "binary_frame")
        self.assertNotIn("binary-private-data", json.dumps(binary))
        self.assertEqual(oversized["kind"], "oversized_frame")
        self.assertNotIn("x" * 100, json.dumps(oversized))

    def test_recorder_is_bounded_and_writes_only_summaries(self):
        with tempfile.TemporaryDirectory() as temporary_root:
            path = Path(temporary_root) / "trace.jsonl"
            recorder = SocketTraceRecorder(path=path, max_bytes=512)
            frame = '42["chatMessage",{"content":"never persist this message"}]'

            results = [recorder.record(frame, "out") for _ in range(20)]
            self.assertIn(False, results)
            self.assertLessEqual(path.stat().st_size, 512)

            lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertTrue(lines)
            self.assertNotIn("never persist this message", path.read_text(encoding="utf-8"))
            self.assertEqual(lines[0]["event"], "chatMessage")
            self.assertEqual(lines[-1]["kind"], "trace_limit_reached")

    def test_default_sidecars_are_bounded_along_with_combined_trace(self):
        with tempfile.TemporaryDirectory() as temporary_root:
            path = Path(temporary_root) / "capture" / "debug-api.txt"
            with patch.dict(os.environ, {"EVA_SOCKET_TRACE_FILE": str(path)}):
                recorder = SocketTraceRecorder(thread_id=2, max_bytes=600)
            for _ in range(30):
                recorder.record('42["chatMessage",{"content":"private body"}]', "in")

            outputs = [
                path,
                path.parent / "websocket.jsonl",
                path.parent / "http-api.jsonl",
            ]
            for output_path in outputs:
                self.assertTrue(output_path.is_file())
                self.assertLessEqual(output_path.stat().st_size, 600)
                self.assertNotIn("private body", output_path.read_text(encoding="utf-8"))

    def test_http_request_and_response_capture_schema_not_private_values(self):
        class FakeRequest:
            url = (
                "https://user:pass@api.chitchat.gg/api/matches/private-match-id/message"
                "?sid=private-sid&token=private-token"
            )
            method = "POST"
            resource_type = "fetch"
            headers = {
                "content-type": "application/json; charset=utf-8",
                "authorization": "private-authorization",
            }
            post_data = json.dumps(
                {
                    "message": "private chat text",
                    "matchId": "private-match-id",
                    "options": {"skip": False},
                }
            )

        class FakeResponse:
            status = 200
            headers = {
                "content-type": "application/json; charset=utf-8",
                "set-cookie": "private-cookie",
            }

            def __init__(self, request):
                self.request = request

            def body(self):
                return b'{"success":true,"message":"private response text"}'

        with tempfile.TemporaryDirectory() as temporary_root:
            path = Path(temporary_root) / "debug-api.txt"
            recorder = SocketTraceRecorder(thread_id=3, path=path)
            request = FakeRequest()
            recorder._on_request(request)
            recorder._on_response(FakeResponse(request))

            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            request_record, response_record = records
            serialized = json.dumps(records)
            self.assertEqual(request_record["source"], "http_request")
            self.assertEqual(request_record["request_id"], response_record["request_id"])
            self.assertEqual(request_record["endpoint_path"], "/api/matches/{id}/message")
            self.assertEqual(request_record["query_keys"], ["sid", "token"])
            self.assertEqual(response_record["status"], 200)
            self.assertGreaterEqual(response_record["elapsed_ms"], 0)
            self.assertIn("authorization", request_record["credential_header_names"])
            self.assertIn("content-type", request_record["header_names"])
            self.assertIn("set-cookie", response_record["credential_header_names"])
            self.assertIn("content-type", response_record["header_names"])
            self.assertIn("string", serialized)
            for secret in (
                "user:pass", "private-sid", "private-token", "private-authorization",
                "private chat text", "private response text", "private-cookie",
                "private-match-id",
            ):
                self.assertNotIn(secret, serialized)

    def test_non_chitchat_network_requests_are_not_captured(self):
        class ExternalRequest:
            url = "https://mail.private.example/api?email=alice@example.test"
            method = "POST"
            resource_type = "fetch"
            headers = {"authorization": "private-auth"}
            post_data = '{"message":"private body"}'

        with tempfile.TemporaryDirectory() as temporary_root:
            path = Path(temporary_root) / "trace.jsonl"
            recorder = SocketTraceRecorder(path=path)
            recorder._on_request(ExternalRequest())

            self.assertFalse(path.exists())

    def test_default_capture_path_is_debug_api_txt_and_starts_fresh(self):
        with tempfile.TemporaryDirectory() as temporary_root:
            path = Path(temporary_root) / "debug-api.txt"
            path.write_text("old trace must be removed\n", encoding="utf-8")
            with patch.dict(os.environ, {"EVA_SOCKET_TRACE_FILE": str(path)}):
                recorder = SocketTraceRecorder(thread_id=7)
            self.assertEqual(recorder.path, path)
            lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(lines[0]["kind"], "capture_started")
            self.assertNotIn("old trace", path.read_text(encoding="utf-8"))
            recorder.record('42["presenceSync"]', "out")

            class FakeRequest:
                url = "https://api.chitchat.gg/api/chat?token=private-token"
                method = "POST"
                resource_type = "fetch"
                headers = {"authorization": "secret-authorization"}
                post_data = '{"content":"private chat text"}'

            recorder._on_request(FakeRequest())
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            self.assertEqual(records[1]["event"], "presenceSync")
            self.assertEqual(records[1]["worker_id"], 7)

            websocket_path = path.parent / "websocket.jsonl"
            http_path = path.parent / "http-api.jsonl"
            self.assertTrue(websocket_path.is_file())
            self.assertTrue(http_path.is_file())
            websocket_records = [
                json.loads(line)
                for line in websocket_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(websocket_records[0]["kind"], "capture_started")
            self.assertEqual(websocket_records[1]["event"], "presenceSync")
            http_records = [
                json.loads(line)
                for line in http_path.read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(http_records[0]["kind"], "capture_started")
            self.assertEqual(http_records[1]["kind"], "api_request")
            self.assertNotIn("private-token", http_path.read_text(encoding="utf-8"))
            self.assertNotIn("secret-authorization", http_path.read_text(encoding="utf-8"))
            self.assertNotIn("private chat text", http_path.read_text(encoding="utf-8"))

    def test_page_attachment_records_sent_and_received_frames(self):
        class FakeSocket:
            url = "wss://api.chitchat.gg/socket.io/?sid=secret"

            def __init__(self):
                self.handlers = {}

            def on(self, event_name, callback):
                self.handlers[event_name] = callback

        class FakePage:
            def __init__(self):
                self.handlers = {}

            def on(self, event_name, callback):
                self.handlers[event_name] = callback

        with tempfile.TemporaryDirectory() as temporary_root:
            path = Path(temporary_root) / "trace.jsonl"
            recorder = SocketTraceRecorder(path=path)
            page = FakePage()
            recorder.attach_page(page)
            required_handlers = {"websocket", "request", "response", "requestfailed", "framenavigated"}
            self.assertTrue(required_handlers.issubset(page.handlers))
            websocket = FakeSocket()
            page.handlers["websocket"](websocket)
            websocket.handlers["framesent"]('42["presenceSync"]')
            websocket.handlers["framereceived"]('42["onlineFriends",[]]')
            websocket.handlers["socketerror"]("private token in error details")
            websocket.handlers["close"]()

            class FakeHandshake:
                url = "wss://api.chitchat.gg/socket.io/?sid=private-sid"
                method = "GET"
                resource_type = "websocket"
                headers = {
                    "authorization": "private-auth",
                    "cookie": "private-cookie",
                }
                post_data = None

            page.handlers["request"](FakeHandshake())
            records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
            frame_records = [record for record in records if "event" in record]
            self.assertEqual([record["direction"] for record in frame_records], ["out", "in"])
            self.assertEqual([record["event"] for record in frame_records], ["presenceSync", "onlineFriends"])
            self.assertEqual(
                [record["kind"] for record in records if record["kind"] in {"websocket_error", "websocket_closed"}],
                ["websocket_error", "websocket_closed"],
            )
            handshake_record = next(
                record for record in records if record["kind"] == "websocket_handshake"
            )
            self.assertEqual(handshake_record["endpoint_path"], "/socket.io/")
            self.assertEqual(
                handshake_record["credential_header_names"], ["authorization", "cookie"]
            )
            self.assertNotIn("secret", path.read_text(encoding="utf-8"))
            for secret in ("private token", "private-sid", "private-auth", "private-cookie"):
                self.assertNotIn(secret, path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
