"""
Mirror of auth-service's crypto so the worker can DECRYPT the Google refresh token that
auth-service encrypted.

Duplicating ~20 lines across two services is the deliberate trade here. The alternative —
a shared library package — means versioning and publishing it, and a mismatch would show
up as undecryptable tokens. In a larger system this would live in an internal package;
at this size, the duplication is cheaper than the coupling, and both copies must simply
derive the key identically.
"""
import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


def _build_fernet() -> Fernet:
    raw_key = os.getenv("TOKEN_ENCRYPTION_KEY") or os.getenv("JWT_SECRET_KEY", "change_me")
    digest = hashlib.sha256(raw_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


_fernet = _build_fernet()


def try_decrypt(ciphertext: str | None) -> str | None:
    if not ciphertext:
        return None
    try:
        return _fernet.decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        return None
