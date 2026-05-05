"""
Read/write app-level settings (sender backend choice, sender credentials).

Resolution order in `get`:
  1. Row in `app_settings` table (decrypted if it's a secret)
  2. Otherwise, the same-named field on `settings` (loaded from .env)
  3. Otherwise, ""

This lets existing .env-based setups keep working unchanged. Once a value
is written via `set`, the DB row wins until it's deleted.
"""
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models import Setting
from app.services import encryption


# Whitelist: maps key → is_secret.
# Anything not in this dict is rejected by set() — defense against arbitrary
# key injection from the API layer.
KEYS: dict[str, bool] = {
    "SENDER_BACKEND":                 False,
    "GMAIL_USERNAME":                 False,
    "GMAIL_APP_PASSWORD":             True,
    "GMAIL_FROM_ADDRESS":             False,
    "GMAIL_FROM_NAME":                False,
    "INSTANTLY_API_KEY":              True,
    "INSTANTLY_DEFAULT_CAMPAIGN_ID":  False,
    "INSTANTLY_API_BASE_URL":         False,
    "REQUIRE_APPROVAL":               False,  # "true" / "false" — default off
    # Send window (all four empty → always-on; any empty → that dimension unconstrained)
    "SCHEDULER_SEND_DAYS":            False,  # CSV of weekday numbers (0=Mon..6=Sun)
    "SCHEDULER_START_HOUR":           False,  # int 0-23, inclusive
    "SCHEDULER_END_HOUR":             False,  # int 0-23, exclusive
    "SCHEDULER_TIMEZONE":             False,  # IANA timezone, e.g. "America/Los_Angeles"
}

# Which keys belong to which logical "backend" — used by the API to scope
# credential views and the sender to load only what it needs.
BACKEND_KEYS: dict[str, list[str]] = {
    "gmail": [
        "GMAIL_USERNAME",
        "GMAIL_APP_PASSWORD",
        "GMAIL_FROM_ADDRESS",
        "GMAIL_FROM_NAME",
    ],
    "instantly": [
        "INSTANTLY_API_KEY",
        "INSTANTLY_DEFAULT_CAMPAIGN_ID",
        "INSTANTLY_API_BASE_URL",
    ],
    "stub": [],
}


class UnknownKey(ValueError):
    pass


def _env_fallback(key: str) -> str:
    """Get the value of `key` from pydantic Settings, treating non-strings as ''."""
    v = getattr(settings, key, "")
    return v if isinstance(v, str) else ""


async def get(db: AsyncSession, key: str) -> str:
    """Return the value of `key`. DB row wins; .env is the fallback; "" otherwise."""
    if key not in KEYS:
        raise UnknownKey(key)
    row = (await db.execute(
        select(Setting).where(Setting.key == key)
    )).scalar_one_or_none()
    if row is not None and row.value:
        if row.is_secret:
            return encryption.decrypt(row.value)
        return row.value
    return _env_fallback(key)


async def set(
    db: AsyncSession,
    key: str,
    value: str,
    user_id: str | None = None,
) -> None:
    """Upsert a setting. Empty string clears the DB row (so the .env fallback
    takes over again). The caller is responsible for committing."""
    if key not in KEYS:
        raise UnknownKey(key)

    row = (await db.execute(
        select(Setting).where(Setting.key == key)
    )).scalar_one_or_none()

    is_secret = KEYS[key]
    stored = encryption.encrypt(value) if is_secret and value else value

    if row is None:
        row = Setting(
            key=key,
            value=stored,
            is_secret=is_secret,
            updated_by_user_id=user_id,
        )
        db.add(row)
    else:
        row.value = stored
        row.is_secret = is_secret
        row.updated_at = datetime.now(timezone.utc)
        row.updated_by_user_id = user_id


async def get_many(db: AsyncSession, keys: Iterable[str]) -> dict[str, str]:
    """Convenience: fetch several keys at once."""
    return {k: await get(db, k) for k in keys}


async def get_creds_for_backend(db: AsyncSession, backend: str) -> dict[str, str]:
    """Load all credential values relevant to a given backend."""
    return await get_many(db, BACKEND_KEYS.get(backend, []))


async def is_set(db: AsyncSession, key: str) -> bool:
    """True if there's a non-empty value (in DB or env)."""
    if key not in KEYS:
        return False
    return bool(await get(db, key))
