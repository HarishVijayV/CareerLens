"""
Everything crypto-related lives here, and nowhere else, on purpose — if you ever need to
audit "how do we handle secrets," this is the one file to read.
"""
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from passlib.context import CryptContext

from app.core.config import settings

# bcrypt automatically generates + stores a random salt per password — that's why two users
# with the same password end up with completely different hashes.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(raw_password: str) -> str:
    return _pwd_context.hash(raw_password)


def verify_password(raw_password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(raw_password, hashed_password)


def create_access_token(user_id: str, role: str) -> str:
    """Short-lived, signed, stateless. Never store this server-side — verifying the
    signature + expiry is enough. This is exactly why it can't be revoked early."""
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
    """Raises jwt.PyJWTError on bad signature / expiry — callers should catch and 401."""
    return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def generate_refresh_token() -> str:
    """Opaque random string, NOT a JWT. Stored (hashed) server-side so it can be revoked
    instantly — that's the whole reason refresh tokens use a different mechanism than
    access tokens."""
    return secrets.token_urlsafe(64)


def hash_refresh_token(raw_token: str) -> str:
    # Refresh tokens are already high-entropy random strings, so a fast hash (sha256) is
    # fine here — unlike passwords, there's no need for bcrypt's deliberate slowness.
    import hashlib

    return hashlib.sha256(raw_token.encode()).hexdigest()


def refresh_token_expiry() -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=settings.refresh_token_expire_days)
