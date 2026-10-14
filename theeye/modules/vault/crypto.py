"""Primitives du coffre : dérivation de clé scrypt + chiffrement AES-256-GCM (bibliothèque `cryptography`)."""
import base64
import hashlib
import os
from typing import Dict

try:
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    AVAILABLE, IMPORT_ERROR = True, ""
except ImportError as e:  # le module reste chargeable : il signale la dépendance manquante
    AVAILABLE, IMPORT_ERROR = False, str(e)
    InvalidTag = Exception  # type: ignore

KDF = {"n": 2 ** 15, "r": 8, "p": 1}
VERIFIER_PLAINTEXT = "theeye-vault-v1"


class DecryptError(Exception):
    pass


def new_salt() -> bytes:
    return os.urandom(16)


def derive_key(passphrase: str, salt: bytes, params: Dict[str, int] = KDF) -> bytes:
    return hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=params["n"], r=params["r"], p=params["p"],
                          maxmem=256 * 1024 * 1024, dklen=32)


def encrypt(key: bytes, plaintext: str, aad: str) -> str:
    nonce = os.urandom(12)
    ct = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), aad.encode("utf-8"))
    return base64.b64encode(nonce + ct).decode("ascii")


def decrypt(key: bytes, token: str, aad: str) -> str:
    try:
        raw = base64.b64decode(token)
        return AESGCM(key).decrypt(raw[:12], raw[12:], aad.encode("utf-8")).decode("utf-8")
    except (InvalidTag, ValueError):
        raise DecryptError("déchiffrement impossible")
