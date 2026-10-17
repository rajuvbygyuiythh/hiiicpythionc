"""Connect to a saved ChitChat session using Socket.IO without launching a browser."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from browser.account_session_store import load_saved_account_sessions
from transport.chitchat_socket import (
    DEFAULT_ENDPOINT,
    DEFAULT_ORIGIN,
    DEFAULT_RELEASE,
    DEFAULT_SOCKETIO_PATH,
    OBSERVED_SERVER_EVENTS,
    ChitchatSocketTransport,
    SocketTransportError,
    summarize_payload_shape,
)


def _parser():
    parser = argparse.ArgumentParser(
        description=(
            "Open a WebSocket-only Socket.IO connection from an existing saved "
            "session. This probe observes server events; it does not start a match "
            "or send chat messages."
        )
    )
    parser.add_argument("--account", required=True, help="Email of a saved account session")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--origin", default=DEFAULT_ORIGIN)
    parser.add_argument("--socketio-path", default=DEFAULT_SOCKETIO_PATH)
    parser.add_argument(
        "--release",
        default=os.environ.get("CHITCHAT_RELEASE", DEFAULT_RELEASE),
        help="Exact captured Socket.IO release value (or set CHITCHAT_RELEASE)",
    )
    parser.add_argument(
        "--token-storage-key",
        default="",
        help="Optional exact localStorage key for Authorization; never guessed or printed",
    )
    parser.add_argument(
        "--token-prefix",
        default="",
        help="Optional exact Authorization prefix for the configured token value",
    )
    return parser


def main(argv=None):
    parser = _parser()
    args = parser.parse_args(argv)
    if not str(args.release or "").strip():
        parser.error(
            "--release (or CHITCHAT_RELEASE) is required; the capture documents the field but not its value"
        )
    account = next(
        (
            item
            for item in load_saved_account_sessions()
            if str(item.get("email") or "").strip().casefold()
            == args.account.strip().casefold()
        ),
        None,
    )
    if account is None:
        parser.error("no saved browser session found for that account")

    def log(message):
        print(message, flush=True)

    transport = ChitchatSocketTransport(
        account,
        endpoint=args.endpoint,
        origin=args.origin,
        socketio_path=args.socketio_path,
        release=args.release,
        token_storage_key=args.token_storage_key,
        token_prefix=args.token_prefix,
        logger=log,
    )
    for event_name in OBSERVED_SERVER_EVENTS:
        transport.on(
            event_name,
            lambda payload, name=event_name: log(
                f"[Socket] Received {name} ({summarize_payload_shape(payload)})"
            ),
        )

    try:
        if not transport.connect():
            log("[Socket] Connection ended before it became active")
            return 1
        log("[Socket] Listening only; Ctrl+C to disconnect")
        transport.wait()
        return 0
    except KeyboardInterrupt:
        log("[Socket] Stopping observer")
        return 0
    except SocketTransportError as error:
        log(f"[Socket] {error}")
        return 1
    except Exception as error:
        log(f"[Socket] Probe failed ({type(error).__name__}); no credential details logged")
        return 1
    finally:
        transport.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
