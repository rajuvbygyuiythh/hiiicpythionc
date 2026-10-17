"""Offline tests for the browserless Socket.IO transport foundation."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from transport.chitchat_socket import (
    DEFAULT_ENDPOINT,
    DEFAULT_ORIGIN,
    OBSERVED_SERVER_EVENTS,
    ChitchatSocketTransport,
    SocketTransportError,
    cookie_header_from_storage_state,
    local_storage_value,
    summarize_payload_shape,
)


class FakeSocketIOClient:
    def __init__(self):
        self.handlers = {}
        self.emissions = []
        self.connect_args = None
        self.connected = False

    def on(self, event_name, handler):
        self.handlers[event_name] = handler

    def connect(self, endpoint, **kwargs):
        self.connect_args = (endpoint, kwargs)
        self.connected = True
        self.handlers["connect"]()

    def emit(self, event_name, *args, **kwargs):
        self.emissions.append((event_name, args, kwargs))

    def wait(self):
        return None

    def disconnect(self):
        self.connected = False
        callback = self.handlers.get("disconnect")
        if callback:
            callback("client disconnect")


class ChitchatSocketTests(unittest.TestCase):
    def test_cookie_header_filters_domain_path_security_and_expiry(self):
        state = {
            "cookies": [
                {"name": "root", "value": "ok", "domain": ".chitchat.gg", "path": "/", "secure": True},
                {"name": "socket", "value": "also-ok", "domain": "api.chitchat.gg", "path": "/socket.io"},
                {"name": "wrong-host", "value": "no", "domain": "notchitchat.gg", "path": "/"},
                {"name": "wrong-path", "value": "no", "domain": "chitchat.gg", "path": "/chat"},
                {"name": "expired", "value": "no", "domain": "chitchat.gg", "path": "/", "expires": 99},
                {"name": "future-secure", "value": "yes", "domain": "api.chitchat.gg", "path": "/", "secure": True, "expires": 200},
            ]
        }
        header = cookie_header_from_storage_state(
            state,
            endpoint=DEFAULT_ENDPOINT,
            socketio_path="socket.io",
            now=100,
        )
        self.assertEqual(header, "root=ok; socket=also-ok; future-secure=yes")
        insecure_header = cookie_header_from_storage_state(
            state,
            endpoint="http://api.chitchat.gg",
            socketio_path="socket.io",
            now=100,
        )
        self.assertEqual(insecure_header, "socket=also-ok")
        subdomain_header = cookie_header_from_storage_state(
            state,
            endpoint="https://ws.api.chitchat.gg",
            socketio_path="socket.io",
            now=100,
        )
        self.assertEqual(subdomain_header, "root=ok")

    def test_local_storage_token_is_only_read_by_exact_configured_key(self):
        state = {
            "origins": [
                {
                    "origin": DEFAULT_ORIGIN,
                    "localStorage": [
                        {"name": "token", "value": "secret-token"},
                        {"name": "other", "value": "other-value"},
                    ],
                }
            ]
        }
        self.assertEqual(local_storage_value(state, "token"), "secret-token")
        self.assertIsNone(local_storage_value(state, "unknown"))
        self.assertIsNone(local_storage_value(state, "token", origin="https://elsewhere.test"))

    def test_connect_is_websocket_only_and_sends_only_observed_presence_event(self):
        with tempfile.TemporaryDirectory() as temporary_root:
            state_path = Path(temporary_root) / "storage_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "cookies": [
                            {
                                "name": "session",
                                "value": "cookie-secret",
                                "domain": "api.chitchat.gg",
                                "path": "/",
                                "secure": True,
                            }
                        ],
                        "origins": [
                            {
                                "origin": DEFAULT_ORIGIN,
                                "localStorage": [
                                    {"name": "selected-session-key", "value": "token-secret"}
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            client = FakeSocketIOClient()
            log_messages = []
            transport = ChitchatSocketTransport(
                {"email": "tester@example.test", "storage_state_path": str(state_path)},
                client=client,
                release="observed-test-release",
                token_storage_key="selected-session-key",
                token_prefix="Token ",
                logger=log_messages.append,
            )
            received = []
            transport.on("chatMessage", received.append)

            self.assertTrue(transport.connect())

            endpoint, options = client.connect_args
            self.assertEqual(endpoint, DEFAULT_ENDPOINT)
            self.assertEqual(options["transports"], ["websocket"])
            self.assertEqual(options["socketio_path"], "socket.io")
            self.assertEqual(options["auth"], {"release": "observed-test-release"})
            self.assertEqual(options["headers"]["Origin"], DEFAULT_ORIGIN)
            self.assertEqual(options["headers"]["Cookie"], "session=cookie-secret")
            self.assertEqual(options["headers"]["Authorization"], "Token token-secret")
            self.assertEqual(client.emissions, [("presenceSync", (), {})])
            self.assertTrue(all("secret" not in message for message in log_messages))

            client.handlers["chatMessage"]({"text": "private message"})
            self.assertEqual(received, [{"text": "private message"}])
            transport.disconnect()
            self.assertFalse(client.connected)

    def test_payload_shape_summary_does_not_include_values_and_sanitizes_keys(self):
        summary = summarize_payload_shape(
            {"message": "private text", "unsafe\nkey": "private token"}
        )
        self.assertIn("message", summary)
        self.assertIn("unsafe_key", summary)
        self.assertNotIn("private", summary)

    def test_token_is_not_guessed_and_unobserved_actions_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary_root:
            state_path = Path(temporary_root) / "storage_state.json"
            state_path.write_text(
                json.dumps(
                    {
                        "cookies": [],
                        "origins": [
                            {
                                "origin": DEFAULT_ORIGIN,
                                "localStorage": [{"name": "token", "value": "must-not-be-used"}],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            transport = ChitchatSocketTransport(
                {"storage_state_path": str(state_path)},
                client=FakeSocketIOClient(),
            )
            self.assertNotIn("Authorization", transport.build_headers())
            self.assertEqual(
                set(OBSERVED_SERVER_EVENTS),
                {"onlineFriends", "matchUpdate", "typing", "chatMessage"},
            )
            with self.assertRaises(ValueError):
                transport.on("findMatch", lambda _payload: None)
            with self.assertRaises(ValueError):
                transport.on("sendMessage", lambda _payload: None)

    def test_missing_or_invalid_saved_state_fails_closed(self):
        transport = ChitchatSocketTransport(
            {"storage_state_path": "/missing/session.json"}, release="test-release"
        )
        with self.assertRaises(SocketTransportError):
            transport.connect()

        with tempfile.TemporaryDirectory() as temporary_root:
            state_path = Path(temporary_root) / "broken.json"
            state_path.write_text("{not-json", encoding="utf-8")
            transport = ChitchatSocketTransport(
                {"storage_state_path": str(state_path)}, release="test-release"
            )
            with self.assertRaises(SocketTransportError):
                transport.connect()

    def test_release_is_required_instead_of_using_a_guessed_value(self):
        client = FakeSocketIOClient()
        transport = ChitchatSocketTransport({}, client=client)
        with self.assertRaisesRegex(SocketTransportError, "release value explicitly"):
            transport.connect()
        self.assertIsNone(client.connect_args)


if __name__ == "__main__":
    unittest.main()
