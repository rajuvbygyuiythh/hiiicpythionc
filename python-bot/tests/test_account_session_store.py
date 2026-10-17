"""Offline tests for saved browser-session/profile persistence."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from browser.account_session_store import (
    get_account_sessions_dir,
    load_saved_account_sessions,
    save_account_session,
)


class FakeContext:
    def storage_state(self, path, indexed_db=True):
        Path(path).write_text(
            json.dumps({"cookies": [{"name": "sid", "value": "test-only"}], "origins": []}),
            encoding="utf-8",
        )


class FakePage:
    url = "https://app.chitchat.gg/start/new"

    def evaluate(self, _script):
        return {"userAgent": "test-agent", "language": "en"}


class AccountSessionStoreTests(unittest.TestCase):
    def test_successful_login_state_is_saved_and_discoverable_for_restore(self):
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            session_dir = save_account_session(
                {"email": "agent@example.test", "password": "not-persisted"},
                FakeContext(),
                FakePage(),
                history=[{"url": FakePage.url, "title": "Chat"}],
                base_dir=root,
            )

            self.assertEqual(session_dir.parent, get_account_sessions_dir(root))
            self.assertTrue((session_dir / "storage_state.json").is_file())
            self.assertTrue((session_dir / "fingerprint.json").is_file())
            self.assertTrue((session_dir / "history.json").is_file())
            metadata = json.loads((session_dir / "metadata.json").read_text(encoding="utf-8"))
            self.assertEqual(metadata["email"], "agent@example.test")
            self.assertNotIn("password", metadata)
            self.assertNotIn("agent@example.test", session_dir.name)

            restored = load_saved_account_sessions(base_dir=root)
            self.assertEqual(len(restored), 1)
            self.assertEqual(restored[0]["email"], "agent@example.test")
            self.assertEqual(Path(restored[0]["storage_state_path"]), session_dir / "storage_state.json")

    def test_profile_folder_is_shared_by_store_and_restore_lookup(self):
        with tempfile.TemporaryDirectory() as temporary_root:
            root = Path(temporary_root)
            expected = root / "account_sessions"
            self.assertEqual(get_account_sessions_dir(root), expected)
            expected.mkdir(parents=True)
            self.assertEqual(load_saved_account_sessions(base_dir=root), [])


if __name__ == "__main__":
    unittest.main()
