"""Pure tests for the encryption helper."""
import pytest

from app.services import encryption as enc


@pytest.fixture(autouse=True)
def _reset_fernet(monkeypatch):
    """Reset the lazy singleton between tests so each test can use a fresh key."""
    monkeypatch.setattr(enc, "_fernet", None)


@pytest.fixture
def with_key(monkeypatch):
    """Provide a real Fernet key for tests that need encryption to work."""
    from cryptography.fernet import Fernet
    key = Fernet.generate_key().decode()
    monkeypatch.setattr(enc.settings, "ENCRYPTION_KEY", key)
    return key


def test_encrypt_decrypt_round_trip(with_key):
    secret = "correct horse battery staple"
    token = enc.encrypt(secret)
    assert token != secret
    assert enc.decrypt(token) == secret


def test_empty_string_is_passthrough(with_key):
    """Empty plaintext stays empty (no point encrypting nothing) — and the
    decrypt path mirrors that so reads of unset rows don't error."""
    assert enc.encrypt("") == ""
    assert enc.decrypt("") == ""


def test_encrypt_without_key_raises(monkeypatch):
    monkeypatch.setattr(enc.settings, "ENCRYPTION_KEY", "")
    with pytest.raises(RuntimeError, match="ENCRYPTION_KEY"):
        enc.encrypt("anything")


def test_decrypt_with_wrong_key_raises(with_key, monkeypatch):
    """Token encrypted under one key shouldn't decrypt under a different one."""
    token = enc.encrypt("hello")
    # Rotate to a different key.
    from cryptography.fernet import Fernet
    monkeypatch.setattr(enc, "_fernet", None)
    monkeypatch.setattr(enc.settings, "ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(ValueError):
        enc.decrypt(token)


def test_decrypt_garbage_raises(with_key):
    with pytest.raises(ValueError):
        enc.decrypt("not-a-real-token")
