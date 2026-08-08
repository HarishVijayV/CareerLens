"""
Everything crypto-related lives here and nowhere else — if you ever need to audit "how
does this system handle secrets", this is the one file to read.

Uses the `bcrypt` library directly rather than passlib. passlib is the more commonly
seen choice in tutorials, but it has been unmaintained since 2020 and breaks against
modern bcrypt releases (it fails at import/hash time with confusing errors). Calling
bcrypt directly is fewer moving parts and makes the 72-byte behaviour below explicit
instead of hidden behind a wrapper.
"""
import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import settings

# bcrypt only ever looks at the first 72 BYTES of input — that's a property of the
# algorithm, not a library limit, and modern bcrypt raises instead of silently
# truncating. Pre-hashing with SHA-256 first means a password of any length maps to a
# fixed 64-char input, so nothing is silently discarded and very long passphrases still
# work. (Passing raw UTF-8 also means "72 bytes" != "72 characters" for non-ASCII.)
def _prehash(raw_password: str) -> bytes:
    return hashlib.sha256(raw_password.encode("utf-8")).hexdigest().encode("ascii")


def hash_password(raw_password: str) -> str:
    # gensalt() generates a fresh random salt per password, which is why two users with
    # the same password end up with completely different stored hashes. The salt is
    # stored inside the resulting hash string — nothing extra to keep track of.
    return bcrypt.hashpw(_prehash(raw_password), bcrypt.gensalt()).decode("ascii")


def verify_password(raw_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(_prehash(raw_password), hashed_password.encode("ascii"))
    except ValueError:
        # Malformed hash in the DB — treat as "no match" rather than raising a 500 that
        # would tell an attacker something about the stored record.
        return False


def create_access_token(user_id: str, role: str) -> str:
    """Short-lived, signed, stateless. Never stored server-side — verifying the signature
    and expiry is enough, which is also exactly why it can't be revoked early."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "role": role,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.access_token_expire_minutes),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError on bad signature or expiry — callers catch and return 401."""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def generate_refresh_token() -> str:
    """Opaque random string, NOT a JWT. Stored (hashed) server-side so it can be revoked
    instantly — the whole reason refresh tokens use a different mechanism from access
    tokens."""
    return secrets.token_urlsafe(64)


def hash_refresh_token(raw_token: str) -> str:
    # Already a high-entropy random string, so a fast hash is correct here. bcrypt's
    # deliberate slowness exists to defend LOW-entropy human passwords against brute
    # force; there's nothing to brute-force in 64 random bytes.
    return hashlib.sha256(raw_token.encode()).hexdigest()


def refresh_token_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
