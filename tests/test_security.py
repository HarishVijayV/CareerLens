"""
Tests for the security-critical code. These are the tests that would actually catch a
regression that matters — password handling and token verification — rather than testing
that FastAPI returns 200.

Run:  pytest tests/ -v
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "services" / "auth-service"))

from app.core.security import (  # noqa: E402
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    hash_password,
    hash_refresh_token,
    verify_password,
)


class TestPasswordHashing:
    def test_hash_is_not_the_password(self):
        assert hash_password("hunter2") != "hunter2"

    def test_same_password_gives_different_hashes(self):
        """Each hash embeds a fresh random salt. If this ever fails, identical passwords
        would be identifiable across accounts from the database alone."""
        assert hash_password("hunter2") != hash_password("hunter2")

    def test_correct_password_verifies(self):
        assert verify_password("hunter2", hash_password("hunter2"))

    def test_wrong_password_rejected(self):
        assert not verify_password("wrong", hash_password("hunter2"))

    def test_very_long_password_works(self):
        """bcrypt only reads the first 72 BYTES, and modern versions raise rather than
        truncate. We SHA-256 pre-hash so any length works — this is the regression test
        for that, and it's the exact bug that broke signup during development."""
        long_password = "a" * 200
        assert verify_password(long_password, hash_password(long_password))

    def test_long_passwords_are_not_interchangeable(self):
        """The failure mode of naive truncation: two passwords sharing a 72-byte prefix
        would both unlock the account. Pre-hashing means the whole string counts."""
        stored = hash_password("a" * 72 + "REAL_ENDING")
        assert not verify_password("a" * 72 + "FAKE_ENDING", stored)

    def test_unicode_password(self):
        password = "पासवर्ड-123-🔑"
        assert verify_password(password, hash_password(password))

    def test_malformed_hash_returns_false_not_crash(self):
        assert not verify_password("anything", "not-a-real-bcrypt-hash")


class TestAccessTokens:
    def test_roundtrip_preserves_identity(self):
        claims = decode_access_token(create_access_token("user-123", "admin"))
        assert claims["sub"] == "user-123"
        assert claims["role"] == "admin"

    def test_tampered_token_is_rejected(self):
        """The whole security value of a JWT: flipping a byte invalidates the signature,
        so a user cannot edit their own role to 'admin'."""
        import jwt

        token = create_access_token("user-123", "user")
        tampered = token[:-4] + ("aaaa" if not token.endswith("aaaa") else "bbbb")
        with pytest.raises(jwt.PyJWTError):
            decode_access_token(tampered)

    def test_token_signed_with_other_secret_is_rejected(self):
        import jwt

        from app.core.config import settings

        forged = jwt.encode({"sub": "attacker", "role": "admin"}, "wrong-secret", algorithm="HS256")
        with pytest.raises(jwt.PyJWTError):
            jwt.decode(forged, settings.jwt_secret_key, algorithms=["HS256"])


class TestRefreshTokens:
    def test_tokens_are_unique_and_long(self):
        tokens = {generate_refresh_token() for _ in range(100)}
        assert len(tokens) == 100
        assert all(len(t) > 40 for t in tokens)

    def test_hash_is_deterministic_but_not_reversible(self):
        raw = generate_refresh_token()
        assert hash_refresh_token(raw) == hash_refresh_token(raw)  # lookups must work
        assert raw not in hash_refresh_token(raw)  # DB leak must not expose the token
