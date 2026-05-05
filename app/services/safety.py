from datetime import datetime,timezone ,timedelta
from sqlalchemy import func,select
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.models import Event,AccountSuppression
class SafetyViolation(Exception):
    pass
async def check_domain_suppressed(db: AsyncSession, domain: str) -> bool:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        select(AccountSuppression).where(
            AccountSuppression.domain == domain,
            (AccountSuppression.expires_at == None) | (AccountSuppression.expires_at > now)
        )
    )
    return result.scalar_one_or_none() is not None  #Domain suppressed or not
    
async def check_bounce_rate(db: AsyncSession, window_days: int = 7) -> float:
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    sent_count = await db.scalar(
        select(func.count(Event.id)).where(
            Event.event_type == "email_sent",
            Event.created_at >= since,
        )
    )
    bounce_count = await db.scalar(
        select(func.count(Event.id)).where(
            Event.event_type == "bounce",
            Event.created_at >= since,
        )
    )
    if not sent_count:
        return 0.0
    return bounce_count / sent_count #Bounce Rate threshold
    
async def check_spam_rate(db: AsyncSession, window_days: int = 7) -> float:
    since = datetime.now(timezone.utc) - timedelta(days=window_days)
    sent_count = await db.scalar(
        select(func.count(Event.id)).where(
            Event.event_type == "email_sent",
            Event.created_at >= since,
        )
    )
    spam_count = await db.scalar(
        select(func.count(Event.id)).where(
            Event.event_type == "spam_complaint",
            Event.created_at >= since,
        )
    )
    if not sent_count:
        return 0.0
    return spam_count / sent_count #Spam rate

async def assert_safe_to_send(db: AsyncSession, domain: str) -> None:
    # Check 1 - domain suppressed?
    if await check_domain_suppressed(db, domain):
        raise SafetyViolation(f"Domain '{domain}' is suppressed.")

    # Check 2 - bounce rate?
    bounce_rate = await check_bounce_rate(db)
    if bounce_rate > settings.MAX_BOUNCE_RATE:
        raise SafetyViolation(
            f"Bounce rate {bounce_rate:.2%} exceeds {settings.MAX_BOUNCE_RATE:.2%}. Sending halted."
        )

    # Check 3 - spam rate?
    spam_rate = await check_spam_rate(db)
    if spam_rate > settings.MAX_SPAM_RATE:
        raise SafetyViolation(
            f"Spam rate {spam_rate:.4%} exceeds {settings.MAX_SPAM_RATE:.4%}. Sending halted."
        )