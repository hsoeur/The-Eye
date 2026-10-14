"""Logique du coffre : état verrouillé/déverrouillé, comptes, usages, audit."""
import base64
import secrets
import threading
import time
from typing import Any, Dict, List, Optional

from ...core.http import HttpError
from . import crypto

KINDS = ("windows", "linux", "database", "application", "service", "autre")
MIN_PASSPHRASE = 12
AUDIT_MAX = 2000


def _s(value: Any, field: str, max_len: int, required: bool = False) -> str:
    v = str(value if value is not None else "").strip()
    if required and not v:
        raise HttpError(400, f"champ requis : {field}")
    if len(v) > max_len:
        raise HttpError(400, f"champ trop long : {field}")
    return v


class VaultService:
    def __init__(self, ctx):
        self.ctx = ctx
        self.store = ctx.store("vault")
        self.lock = threading.RLock()
        self.data: Dict[str, Any] = self._load()
        self.key: Optional[bytes] = None
        self.last_activity = 0.0
        self.failures = 0
        self.locked_until = 0.0
        self.auto_lock_s = float(ctx.config.get("auto_lock_min", 10)) * 60
        self.stale_days = int(ctx.config.get("rotation_days", 90))

    def _load(self) -> Dict[str, Any]:
        d = self.store.load()
        d.setdefault("meta", None)
        d.setdefault("accounts", {})
        d.setdefault("audit", [])
        return d

    def _save(self) -> None:
        self.store.save(self.data)

    # --- état ---------------------------------------------------------------
    @property
    def initialized(self) -> bool:
        return bool(self.data["meta"])

    def _expire(self) -> None:
        if self.key and self.auto_lock_s and time.time() - self.last_activity > self.auto_lock_s:
            self.key = None

    @property
    def unlocked(self) -> bool:
        with self.lock:
            self._expire()
            return self.key is not None

    def _need_key(self) -> bytes:
        with self.lock:
            self._expire()
            if not self.key:
                raise HttpError(423, "coffre verrouillé")
            self.last_activity = time.time()
            return self.key

    def status(self) -> Dict[str, Any]:
        with self.lock:
            self._expire()
            return {"available": crypto.AVAILABLE, "error": crypto.IMPORT_ERROR, "initialized": self.initialized,
                    "unlocked": self.key is not None, "auto_lock_s": self.auto_lock_s,
                    "min_passphrase": MIN_PASSPHRASE, "kinds": list(KINDS), "count": len(self.data["accounts"]),
                    "retry_in_s": max(0, round(self.locked_until - time.time()))}

    def _audit(self, action: str, acc: Optional[Dict[str, Any]], client: str) -> None:
        self.data["audit"].append({"t": time.time(), "action": action, "client": client,
                                   "account_id": acc["id"] if acc else None, "label": acc["label"] if acc else ""})
        del self.data["audit"][:-AUDIT_MAX]
        self.ctx.emit("vault_" + action, f"Coffre : {action}" + (f" « {acc['label']} »" if acc else ""), "info",
                      client=client)

    # --- verrouillage -------------------------------------------------------
    def _check_passphrase(self, passphrase: str) -> bytes:
        if not crypto.AVAILABLE:
            raise HttpError(503, "dépendance manquante : pip install cryptography")
        now = time.time()
        if now < self.locked_until:
            raise HttpError(429, f"trop d'échecs, réessayez dans {round(self.locked_until - now)} s")
        meta = self.data["meta"]
        key = crypto.derive_key(passphrase, base64.b64decode(meta["salt"]), meta["kdf"])
        try:
            crypto.decrypt(key, meta["verifier"], "verifier")
        except crypto.DecryptError:
            self.failures += 1
            self.locked_until = time.time() + min(2 ** self.failures, 60)
            raise HttpError(403, "phrase secrète incorrecte")
        self.failures = 0
        return key

    def setup(self, passphrase: str, client: str) -> None:
        if not crypto.AVAILABLE:
            raise HttpError(503, "dépendance manquante : pip install cryptography")
        with self.lock:
            if self.initialized:
                raise HttpError(409, "coffre déjà initialisé")
            if len(passphrase) < MIN_PASSPHRASE:
                raise HttpError(400, f"phrase secrète trop courte ({MIN_PASSPHRASE} caractères minimum)")
            salt = crypto.new_salt()
            key = crypto.derive_key(passphrase, salt)
            self.data["meta"] = {"salt": base64.b64encode(salt).decode(), "kdf": crypto.KDF,
                                 "verifier": crypto.encrypt(key, crypto.VERIFIER_PLAINTEXT, "verifier")}
            self.key, self.last_activity = key, time.time()
            self._audit("setup", None, client)
            self._save()

    def unlock(self, passphrase: str, client: str) -> None:
        with self.lock:
            if not self.initialized:
                raise HttpError(409, "coffre non initialisé")
            self.key, self.last_activity = self._check_passphrase(passphrase), time.time()
            self._audit("unlock", None, client)
            self._save()

    def lock_now(self, client: str) -> None:
        with self.lock:
            if self.key:
                self.key = None
                self._audit("lock", None, client)
                self._save()

    def change_passphrase(self, old: str, new: str, client: str) -> None:
        with self.lock:
            old_key = self._check_passphrase(old)
            if len(new) < MIN_PASSPHRASE:
                raise HttpError(400, f"phrase secrète trop courte ({MIN_PASSPHRASE} caractères minimum)")
            salt = crypto.new_salt()
            key = crypto.derive_key(new, salt)
            for a in self.data["accounts"].values():
                a["secret"] = crypto.encrypt(key, crypto.decrypt(old_key, a["secret"], a["id"]), a["id"])
            self.data["meta"] = {"salt": base64.b64encode(salt).decode(), "kdf": crypto.KDF,
                                 "verifier": crypto.encrypt(key, crypto.VERIFIER_PLAINTEXT, "verifier")}
            self.key, self.last_activity = key, time.time()
            self._audit("change_passphrase", None, client)
            self._save()

    # --- comptes ------------------------------------------------------------
    @staticmethod
    def _usages(raw: Any) -> List[Dict[str, str]]:
        if not isinstance(raw, list) or len(raw) > 100:
            raise HttpError(400, "usages invalides")
        out = []
        for u in raw:
            if not isinstance(u, dict):
                raise HttpError(400, "usages invalides")
            item = {"host_id": _s(u.get("host_id"), "host_id", 64), "machine": _s(u.get("machine"), "machine", 120),
                    "poste": _s(u.get("poste"), "poste", 120), "usage": _s(u.get("usage"), "usage", 200)}
            if any(item.values()):
                out.append(item)
        return out

    def _public(self, a: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in a.items() if k != "secret"}

    def list(self) -> List[Dict[str, Any]]:
        self._need_key()
        with self.lock:
            return sorted((self._public(a) for a in self.data["accounts"].values()), key=lambda a: a["label"].lower())

    def _fields(self, b: Dict[str, Any]) -> Dict[str, Any]:
        kind = _s(b.get("kind") or "autre", "kind", 20)
        if kind not in KINDS:
            raise HttpError(400, "type invalide")
        return {"label": _s(b.get("label"), "libellé", 120, True), "username": _s(b.get("username"), "identifiant", 200, True),
                "kind": kind, "notes": _s(b.get("notes"), "notes", 2000), "usages": self._usages(b.get("usages", []))}

    def create(self, b: Dict[str, Any], client: str) -> Dict[str, Any]:
        key = self._need_key()
        fields = self._fields(b)
        secret = _s(b.get("secret"), "mot de passe", 1000, True)
        with self.lock:
            now = time.time()
            aid = secrets.token_hex(8)
            acc = {"id": aid, **fields, "secret": crypto.encrypt(key, secret, aid),
                   "created_at": now, "updated_at": now, "rotated_at": now}
            self.data["accounts"][aid] = acc
            self._audit("create", acc, client)
            self._save()
            return self._public(acc)

    def update(self, aid: str, b: Dict[str, Any], client: str) -> Dict[str, Any]:
        key = self._need_key()
        with self.lock:
            acc = self._get(aid)
            acc.update(self._fields(b))
            acc["updated_at"] = time.time()
            if b.get("secret"):
                acc["secret"] = crypto.encrypt(key, _s(b["secret"], "mot de passe", 1000, True), aid)
                acc["rotated_at"] = acc["updated_at"]
            self._audit("update", acc, client)
            self._save()
            return self._public(acc)

    def delete(self, aid: str, client: str) -> None:
        self._need_key()
        with self.lock:
            acc = self._get(aid)
            del self.data["accounts"][aid]
            self._audit("delete", acc, client)
            self._save()

    def reveal(self, aid: str, passphrase: str, client: str) -> str:
        self._need_key()
        with self.lock:
            key = self._check_passphrase(passphrase)
            acc = self._get(aid)
            try:
                secret = crypto.decrypt(key, acc["secret"], aid)
            except crypto.DecryptError:
                raise HttpError(500, "secret illisible (données altérées)")
            self._audit("reveal", acc, client)
            self._save()
            return secret

    def _get(self, aid: str) -> Dict[str, Any]:
        acc = self.data["accounts"].get(aid)
        if not acc:
            raise HttpError(404, "compte introuvable")
        return acc

    def audit(self, limit: int = 200) -> List[Dict[str, Any]]:
        self._need_key()
        with self.lock:
            return list(reversed(self.data["audit"][-limit:]))

    # --- supervision --------------------------------------------------------
    def stale_count(self) -> int:
        if not self.stale_days:
            return 0
        limit = time.time() - self.stale_days * 86400
        with self.lock:
            return sum(1 for a in self.data["accounts"].values() if a["rotated_at"] < limit)
