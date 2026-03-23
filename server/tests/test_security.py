"""Tests for JWT security module — password hashing + token encode/decode.

Tests are designed for robustness:
- Edge cases: empty strings, very long passwords, unicode, special chars
- Token expiry verification
- Token type enforcement (access vs refresh)
- Tampered token detection
"""

import time

import pytest

from server.app.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
)


# ── Password hashing ──────────────────────────────────────────────

class TestPasswordHashing:
    def test_hash_differs_from_plaintext(self):
        pw = "testpassword123"
        hashed = hash_password(pw)
        assert hashed != pw

    def test_verify_correct_password(self):
        pw = "testpassword123"
        hashed = hash_password(pw)
        assert verify_password(pw, hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("correct")
        assert verify_password("wrong", hashed) is False

    def test_same_password_produces_different_hashes(self):
        """bcrypt uses random salt — same input must give different hashes."""
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2
        # But both should verify
        assert verify_password("same", h1)
        assert verify_password("same", h2)

    def test_unicode_password(self):
        pw = "密码测试123！@#"
        hashed = hash_password(pw)
        assert verify_password(pw, hashed)
        assert not verify_password("密码测试123！@", hashed)

    def test_long_password(self):
        """bcrypt truncates at 72 bytes, but our API should still work."""
        pw = "a" * 100
        hashed = hash_password(pw)
        assert verify_password(pw, hashed)

    def test_empty_password(self):
        """Empty passwords should still be hashable (policy enforcement is elsewhere)."""
        pw = ""
        hashed = hash_password(pw)
        assert verify_password(pw, hashed)
        assert not verify_password("notempty", hashed)

    def test_special_characters_password(self):
        pw = r"p@$$w0rd!#%^&*(){}[]|\\:\";<>,.?/~`"
        hashed = hash_password(pw)
        assert verify_password(pw, hashed)


# ── Access token ───────────────────────────────────────────────────

class TestAccessToken:
    def test_create_and_decode(self):
        token = create_access_token({"sub": "admin", "user_id": 1})
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "admin"
        assert payload["user_id"] == 1
        assert payload["type"] == "access"

    def test_contains_exp_claim(self):
        token = create_access_token({"sub": "u"})
        payload = decode_token(token)
        assert "exp" in payload

    def test_preserves_extra_data(self):
        token = create_access_token({"sub": "u", "role": "admin", "custom": 42})
        payload = decode_token(token)
        assert payload["role"] == "admin"
        assert payload["custom"] == 42


# ── Refresh token ──────────────────────────────────────────────────

class TestRefreshToken:
    def test_create_and_decode(self):
        token = create_refresh_token({"sub": "admin", "user_id": 1})
        payload = decode_token(token)
        assert payload is not None
        assert payload["sub"] == "admin"
        assert payload["type"] == "refresh"

    def test_refresh_and_access_tokens_differ(self):
        data = {"sub": "user", "user_id": 1}
        access = create_access_token(data)
        refresh = create_refresh_token(data)
        assert access != refresh

    def test_refresh_token_type_is_refresh(self):
        token = create_refresh_token({"sub": "u"})
        payload = decode_token(token)
        assert payload["type"] == "refresh"


# ── Token validation / error handling ─────────────────────────────

class TestTokenValidation:
    def test_decode_invalid_token_returns_none(self):
        assert decode_token("invalid.token.here") is None

    def test_decode_empty_string_returns_none(self):
        assert decode_token("") is None

    def test_decode_random_garbage_returns_none(self):
        assert decode_token("aGVsbG8=") is None

    def test_decode_tampered_token_returns_none(self):
        """Modifying a single character should invalidate the signature."""
        token = create_access_token({"sub": "user"})
        # Flip last character
        tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
        assert decode_token(tampered) is None

    def test_decode_none_type_raises_or_returns_none(self):
        """Passing None should not crash."""
        try:
            result = decode_token(None)  # type: ignore
            assert result is None
        except (TypeError, AttributeError):
            pass  # Also acceptable — just shouldn't crash unexpectedly

    def test_expired_token_returns_none(self):
        """Token with 0-second expiry should be expired immediately."""
        from server.app.config import settings
        original = settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
        try:
            settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES = 0
            token = create_access_token({"sub": "u"})
            # Small sleep to ensure expiry
            time.sleep(1)
            assert decode_token(token) is None
        finally:
            settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES = original
