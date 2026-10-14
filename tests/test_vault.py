import tempfile
import time
import unittest
from pathlib import Path

from theeye.core.config import Settings
from theeye.core.http import HttpError
from theeye.core.module import Context, Shared
from theeye.modules.vault import crypto
from theeye.modules.vault.service import VaultService

PASS = "correct horse battery"


def make(tmp, **cfg):
    s = Settings(data_dir=Path(tmp), modules={"vault": cfg})
    bus = type("B", (), {"publish": lambda *a, **k: None})()
    return VaultService(Context(Shared(s, bus, None, None), "vault"))


ACC = {"label": "SQL prod", "username": "sa", "kind": "database", "secret": "S3cret!",
       "usages": [{"host_id": "h1", "machine": "SRV-SQL", "poste": "", "usage": "service SQL"}]}


class VaultTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.v = make(self.tmp.name)

    def test_locked_until_setup_and_short_passphrase_rejected(self):
        with self.assertRaises(HttpError) as e:
            self.v.list()
        self.assertEqual(e.exception.status, 423)
        with self.assertRaises(HttpError):
            self.v.setup("court", "c")

    def test_secret_encrypted_at_rest_and_revealed(self):
        self.v.setup(PASS, "c")
        acc = self.v.create(ACC, "c")
        self.assertNotIn("secret", acc)
        self.assertNotIn("S3cret!", (Path(self.tmp.name) / "vault.json").read_text(encoding="utf-8"))
        self.assertEqual(self.v.reveal(acc["id"], PASS, "c"), "S3cret!")
        self.assertEqual(self.v.audit()[0]["action"], "reveal")

    def test_unlock_after_restart_and_wrong_passphrase_throttled(self):
        self.v.setup(PASS, "c")
        acc = self.v.create(ACC, "c")
        v2 = make(self.tmp.name)
        self.assertFalse(v2.unlocked)
        with self.assertRaises(HttpError) as e:
            v2.unlock("mauvaise phrase secrète", "c")
        self.assertEqual(e.exception.status, 403)
        with self.assertRaises(HttpError) as e:
            v2.unlock(PASS, "c")
        self.assertEqual(e.exception.status, 429)
        v2.locked_until = 0
        v2.unlock(PASS, "c")
        self.assertEqual(v2.reveal(acc["id"], PASS, "c"), "S3cret!")

    def test_auto_lock(self):
        v = make(self.tmp.name, auto_lock_min=1)
        v.setup(PASS, "c")
        v.last_activity -= 120
        self.assertFalse(v.unlocked)

    def test_change_passphrase_reencrypts(self):
        self.v.setup(PASS, "c")
        acc = self.v.create(ACC, "c")
        self.v.change_passphrase(PASS, "another long passphrase", "c")
        self.assertEqual(self.v.reveal(acc["id"], "another long passphrase", "c"), "S3cret!")

    def test_ciphertext_bound_to_account(self):
        key = crypto.derive_key(PASS, crypto.new_salt())
        token = crypto.encrypt(key, "x", "a")
        with self.assertRaises(crypto.DecryptError):
            crypto.decrypt(key, token, "b")

    def test_stale_and_update_rotation(self):
        self.v.setup(PASS, "c")
        acc = self.v.create(ACC, "c")
        self.v.data["accounts"][acc["id"]]["rotated_at"] = time.time() - 200 * 86400
        self.assertEqual(self.v.stale_count(), 1)
        self.v.update(acc["id"], {**ACC, "secret": "new"}, "c")
        self.assertEqual(self.v.stale_count(), 0)
        self.v.delete(acc["id"], "c")
        self.assertEqual(self.v.list(), [])


if __name__ == "__main__":
    unittest.main()
