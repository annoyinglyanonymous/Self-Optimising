"""
Sender abstraction. Routes outbound messages to the configured backend.

The active backend is read from app_settings (DB → .env fallback) on every
call so changes through the Settings UI take effect without a restart.

Backends:
    "stub"       — log only. Use for dev.
    "gmail"      — send via Gmail SMTP.
    "instantly"  — push to an Instantly campaign.
"""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.services import app_settings

log = logging.getLogger(__name__)


async def _resolve_backend(db: AsyncSession) -> str:
    backend = (await app_settings.get(db, "SENDER_BACKEND") or settings.SENDER_BACKEND or "stub").lower()
    return backend


async def send(
    *,
    db: AsyncSession,
    email: str,
    first_name: str | None,
    last_name: str | None,
    company: str | None,
    template_family: str,
    subject: str,
    body: str,
) -> str:
    """Send a message. Returns a provider-specific reference id (may be "")."""
    backend = await _resolve_backend(db)

    if backend == "stub":
        log.info("[stub-sender] would send to=%s subject=%r", email, subject)
        return ""

    if backend == "gmail":
        from app.services.gmail_client import send_email
        creds = await app_settings.get_creds_for_backend(db, "gmail")
        return await send_email(
            creds=creds,
            to_email=email,
            to_name=" ".join(filter(None, [first_name, last_name])) or None,
            subject=subject,
            body=body,
        )

    if backend == "instantly":
        from app.services.instantly_client import push_lead
        creds = await app_settings.get_creds_for_backend(db, "instantly")
        # campaign_map still lives in env-only — bulk per-segment routing is
        # documented as out-of-scope for the credential-management feature.
        return await push_lead(
            creds=creds,
            campaign_map=settings.INSTANTLY_CAMPAIGN_MAP,
            email=email,
            first_name=first_name,
            last_name=last_name,
            company=company,
            template_family=template_family,
            custom_subject=subject,
            custom_body=body,
        )

    raise RuntimeError(f"unknown SENDER_BACKEND={backend!r}")
