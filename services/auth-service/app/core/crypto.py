"""
Encryption for third-party tokens at rest.

Password hashing and this are different problems and need different tools. A password is
verified, never recovered — so it gets a one-way hash (bcrypt). A Google refresh token
has to be *used* later, so it must be reversible — that means encryption, not hashing.
Confusing the two is a classic mistake in both directions.

Fernet (AES-128-CBC + HMAC) is authenticated encryption: tampering with the ciphertext
makes decryption fail loudly rather than silently returning garbage.

The key comes from TOKEN_ENCRYPTION_KEY. If it isn't set, it's derived from JWT_SECRET_KEY
so the app still runs in development — but that's a dev convenience, and rotating the JWT
secret would then orphan every stored token. Set both explicitly for anything real.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _build_fernet() -> Fernet:
    raw_key = settings.token_encryption_key or settings.jwt_secret_key
    # Fernet needs exactly 32 url-safe base64 bytes; SHA-256 gives a stable 32 bytes from
    # any passphrase, so the operator doesn't have to generate a special-format key.
    digest = hashlib.sha256(raw_key.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


_fernet = _build_fernet()


def encrypt(plaintext: str) -> str:
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """Raises InvalidToken if the data was tampered with or the key changed."""
    return _fernet.decrypt(ciphertext.encode()).decode()


def try_decrypt(ciphertext: str | None) -> str | None:
    """Non-raising variant for optional fields — a rotated key shouldn't 500 the app,
    it should look like 'no stored token' and prompt a re-connect."""
    if not ciphertext:
        return None
    try:
        return decrypt(ciphertext)
    except InvalidToken:
        return None
