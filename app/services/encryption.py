"""
Symmetric encryption for credential values stored in the DB.

Master key (Fernet, 32 random bytes base64-encoded) lives in .env as
ENCRYPTION_KEY. Generate one with:

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

WARNING: rotating the key invalidates every previously stored secret —
they become undecryptable. Treat the key like a backup-it-now password.
"""
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """Lazy singleton — only constructs Fernet when first needed, so the app
    boots without an encryption key set (read-from-env paths still work)."""
    global _fernet
    if _fernet is not None:
        return _fernet
    key = settings.ENCRYPTION_KEY
    if not key:
        raise RuntimeError(
            "ENCRYPTION_KEY is empty. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"` and put it in .env."
        )
    _fernet = Fernet(key.encode("utf-8"))
    return _fernet


def encrypt(plain: str) -> str:
    """Encrypt a string. Returns base64-encoded Fernet token (str-safe)."""
    if plain == "":
        return ""
    return _get_fernet().encrypt(plain.encode("utf-8")).decode("utf-8")


def decrypt(token: str) -> str:
    """Decrypt a token produced by encrypt(). Raises ValueError if the token
    is invalid (wrong key, corruption, plaintext slipped in)."""
    if token == "":
        return ""
    try:
        return _get_fernet().decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as e:
        raise ValueError("Invalid encryption token (key mismatch or corrupt data)") from e
