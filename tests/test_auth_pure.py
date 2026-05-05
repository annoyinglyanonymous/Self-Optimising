"""Pure (no-DB) tests for auth primitives."""
import os

import pytest

from app.services import auth as auth_service


# JWT tests need a secret. Stub one for the duration of these tests.
@pytest.fixture(autouse=True)
def jwt_secret(monkeypatch):
    monkeypatch.setattr(auth_service.settings, "JWT_SECRET", "test-secret-not-for-prod")


def test_hash_password_produces_different_hash_each_time():
    """bcrypt salts ensure two hashes of the same password don't match."""
    p = "correct horse battery staple"
    h1 = auth_service.hash_password(p)
    h2 = auth_service.hash_password(p)
    assert h1 != h2


def test_verify_password_accepts_correct():
    p = "correct horse battery staple"
    h = auth_service.hash_password(p)
    assert auth_service.verify_password(p, h) is True


def test_verify_password_rejects_wrong():
    h = auth_service.hash_password("right")
    assert auth_service.verify_password("wrong", h) is False


def test_verify_password_handles_garbage_hash():
    """A malformed hash should return False, not raise."""
    assert auth_service.verify_password("anything", "not-a-real-hash") is False
    assert auth_service.verify_password("anything", "") is False


def test_token_round_trip():
    token = auth_service.create_access_token("user-uuid-123", "alice@example.com")
    payload = auth_service.decode_access_token(token)
    assert payload["sub"] == "user-uuid-123"
    assert payload["email"] == "alice@example.com"
    assert "exp" in payload
    assert "iat" in payload


def test_token_with_wrong_secret_fails(monkeypatch):
    token = auth_service.create_access_token("user-uuid-123", "alice@example.com")
    # Rotate the secret — old tokens should no longer verify.
    monkeypatch.setattr(auth_service.settings, "JWT_SECRET", "different-secret")
    import jwt
    with pytest.raises(jwt.InvalidTokenError):
        auth_service.decode_access_token(token)


def test_create_token_without_secret_raises(monkeypatch):
    monkeypatch.setattr(auth_service.settings, "JWT_SECRET", "")
    with pytest.raises(RuntimeError, match="JWT_SECRET"):
        auth_service.create_access_token("uid", "e@x.com")
