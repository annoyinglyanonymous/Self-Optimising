"""Settings endpoints for the dashboard.

Reads + writes flow through app_settings (DB → .env fallback). Secrets are
masked as "***" on read, and a submitted "***" on write means "no change"
so the UI can re-submit forms safely.
"""
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import User
from app.services import app_settings
from app.services.auth import current_user

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(current_user)],
)

VALID_BACKENDS = {"stub", "gmail", "instantly"}
SECRET_MASK = "***"


@router.get("/sender-status")
async def sender_status(db: AsyncSession = Depends(get_db)):
    """Which sender backend is active, and is each one configured?"""
    active = (await app_settings.get(db, "SENDER_BACKEND") or "stub").lower()
    backends: dict[str, dict] = {}
    for name, keys in app_settings.BACKEND_KEYS.items():
        missing = []
        for k in keys:
            if app_settings.KEYS[k] is False:
                continue  # only required-secret-ish keys gate readiness here
            if not await app_settings.get(db, k):
                missing.append(k)
        # Gmail also needs the username (non-secret) and Instantly the campaign id.
        if name == "gmail" and not await app_settings.get(db, "GMAIL_USERNAME"):
            missing.append("GMAIL_USERNAME")
        if name == "instantly" and not await app_settings.get(db, "INSTANTLY_DEFAULT_CAMPAIGN_ID"):
            missing.append("INSTANTLY_DEFAULT_CAMPAIGN_ID")
        backends[name] = {"ready": not missing, "missing": missing}
    return {"active": active, "backends": backends}


@router.get("/credentials")
async def get_credentials(db: AsyncSession = Depends(get_db)):
    """Return all known credential keys.

    Secrets are masked as "***" if set, "" if unset. Plain values come back
    as-is. The frontend uses this to render the form."""
    out: dict[str, dict[str, Any]] = {"sender_backend": {"value": (await app_settings.get(db, "SENDER_BACKEND") or "stub")}}

    for backend, keys in app_settings.BACKEND_KEYS.items():
        bucket: dict[str, Any] = {}
        for k in keys:
            raw = await app_settings.get(db, k)
            is_secret = app_settings.KEYS[k]
            bucket[k] = {
                "value": (SECRET_MASK if is_secret and raw else raw if not is_secret else ""),
                "is_secret": is_secret,
                "is_set": bool(raw),
            }
        out[backend] = bucket

    # Non-secret behavior flags that don't belong to any backend bucket.
    out["behavior"] = {
        "REQUIRE_APPROVAL": await app_settings.get(db, "REQUIRE_APPROVAL"),
        "SCHEDULER_SEND_DAYS": await app_settings.get(db, "SCHEDULER_SEND_DAYS"),
        "SCHEDULER_START_HOUR": await app_settings.get(db, "SCHEDULER_START_HOUR"),
        "SCHEDULER_END_HOUR": await app_settings.get(db, "SCHEDULER_END_HOUR"),
        "SCHEDULER_TIMEZONE": await app_settings.get(db, "SCHEDULER_TIMEZONE"),
    }
    return out


class CredentialUpdate(BaseModel):
    values: dict[str, str]


@router.put("/credentials")
async def put_credentials(
    payload: CredentialUpdate,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(current_user),
):
    """Update one or more credentials.

    - Each key must be in the whitelist (app_settings.KEYS).
    - For secret keys, a submitted value of SECRET_MASK ("***") is a no-op
      (so the UI can re-submit the masked form without losing the secret).
    - Empty string clears the DB row → falls back to .env.
    """
    updated: list[str] = []
    for key, value in payload.values.items():
        if key not in app_settings.KEYS:
            raise HTTPException(status_code=400, detail=f"unknown key: {key}")
        if app_settings.KEYS[key] and value == SECRET_MASK:
            continue  # leave existing secret untouched
        await app_settings.set(db, key, value, user_id=str(user.id) if user else None)
        updated.append(key)
    await db.commit()
    return {"updated": updated}


class BackendChoice(BaseModel):
    backend: str


@router.post("/sender-backend")
async def set_sender_backend(
    payload: BackendChoice,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(current_user),
):
    if payload.backend not in VALID_BACKENDS:
        raise HTTPException(
            status_code=400,
            detail=f"backend must be one of {sorted(VALID_BACKENDS)}",
        )
    await app_settings.set(
        db, "SENDER_BACKEND", payload.backend,
        user_id=str(user.id) if user else None,
    )
    await db.commit()
    return {"backend": payload.backend}


class TestConnectionRequest(BaseModel):
    backend: str


@router.post("/test-connection")
async def test_connection(
    payload: TestConnectionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Authenticate against the configured backend without sending."""
    backend = payload.backend.lower()
    if backend == "stub":
        return {"ok": True, "error": None}

    creds = await app_settings.get_creds_for_backend(db, backend)

    if backend == "gmail":
        from app.services.gmail_client import test_connection as gmail_test
        ok, err = await gmail_test(creds)
        return {"ok": ok, "error": err}

    if backend == "instantly":
        from app.services.instantly_client import test_connection as inst_test
        ok, err = await inst_test(creds)
        return {"ok": ok, "error": err}

    raise HTTPException(status_code=400, detail=f"unsupported backend: {backend}")
