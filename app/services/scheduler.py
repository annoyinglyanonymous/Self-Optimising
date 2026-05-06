"""
Background scheduler — finds leads due for the next touch and runs the full
generate→send pipeline against them.

One tick:
  1. Skip if outside the configured send window
     (SCHEDULER_SEND_DAYS / START_HOUR / END_HOUR / TIMEZONE in app_settings,
     falling back to .env). Empty values are unconstraining.
  2. Pull eligible leads: enriched, with a persona, no terminal event, under
     the per-persona max_touches, last touch older than touch_spacing_days.
  3. For each lead in its own session: run safety check, ask the bandit for a
     (channel, angle), draft the message, write a Touch, and either send via
     the configured backend (SENDER_BACKEND) or leave the touch as
     pending_approval if REQUIRE_APPROVAL is on.

Disabled by default (SCHEDULER_ENABLED=false) — turn it on only after a real
sender backend is configured, otherwise it just queues drafts.
"""
import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, func

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import Lead, Touch, Event
from app.services.policy_engine import decide_policy, get_pacing
from app.services.message_gen import generate_email
from app.services.safety import assert_safe_to_send, SafetyViolation
from app.services.sender import send as send_message
from app.services import app_settings

log = logging.getLogger(__name__)
_scheduler: AsyncIOScheduler | None = None

# Once any of these has fired for a lead, we stop sequencing them.
TERMINAL_EVENT_TYPES = {
    "reply_classified_positive",
    "reply_classified_objection",
    "reply_classified_unsubscribe",
    "reply_classified_wrong_contact",
    "unsubscribe",
    "bounce",
    "spam_complaint",
}


def _parse_days(days: str) -> set[int] | None:
    """Parse a SCHEDULER_SEND_DAYS value (CSV of weekday numbers,
    0=Monday..6=Sunday). The string is sourced from app_settings (DB row wins,
    .env fallback). Returns None when empty or unparseable — no day filter."""
    if not days or not days.strip():
        return None
    out: set[int] = set()
    for chunk in days.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            n = int(chunk)
        except ValueError:
            continue
        if 0 <= n <= 6:
            out.add(n)
    return out or None


def _parse_hour(hour_str: str) -> int | None:
    if not hour_str or not hour_str.strip():
        return None
    try:
        h = int(hour_str.strip())
    except ValueError:
        return None
    return h if 0 <= h <= 23 else None


def _resolve_tz(tz_name: str):
    """Best-effort TZ lookup. Falls back to UTC on empty / invalid input."""
    if not tz_name or not tz_name.strip():
        return timezone.utc
    try:
        return ZoneInfo(tz_name.strip())
    except ZoneInfoNotFoundError:
        return timezone.utc


def is_in_send_window(
    now: datetime,
    days: str,
    start_hour: str,
    end_hour: str,
    timezone_name: str,
) -> bool:
    """Pure: True iff `now` falls within the configured send window.

    Empty inputs are unconstraining: when all four args are empty, returns True
    (legacy always-on behavior). Time-of-day is checked in [start, end), where
    end_hour is exclusive — `start=9, end=17` covers 09:00:00 through 16:59:59.
    Days are Python weekday numbers (Mon=0..Sun=6) compared against `now`'s
    weekday in the configured timezone.
    """
    allowed_days = _parse_days(days)
    sh = _parse_hour(start_hour)
    eh = _parse_hour(end_hour)
    tz = _resolve_tz(timezone_name)

    # No constraints at all → always in window.
    if allowed_days is None and sh is None and eh is None and timezone_name in (None, "", " "):
        return True

    local = now.astimezone(tz)
    if allowed_days is not None and local.weekday() not in allowed_days:
        return False
    if sh is not None and local.hour < sh:
        return False
    if eh is not None and local.hour >= eh:
        return False
    return True


async def _has_terminal_event(db, lead_id) -> bool:
    n = await db.scalar(
        select(func.count(Event.id)).where(
            Event.lead_id == lead_id,
            Event.event_type.in_(TERMINAL_EVENT_TYPES),
        )
    )
    return bool(n)


async def _find_eligible_leads(db, limit: int) -> list[Lead]:
    """Leads that are: enriched, have a persona, no terminal event, under
    max_touches for their persona, and last touch is older than spacing."""
    now = datetime.now(timezone.utc)

    # Pull a generous candidate set; we filter in Python because the per-persona
    # spacing/max rules don't fit a single SQL query cleanly.
    candidates = (await db.execute(
        select(Lead)
        .where(
            Lead.persona.is_not(None),
            Lead.enrichment_status == "complete",
        )
        .order_by(Lead.created_at.asc())
        .limit(limit * 5)
    )).scalars().all()

    eligible: list[Lead] = []
    for lead in candidates:
        if await _has_terminal_event(db, lead.id):
            continue

        rule = get_pacing(lead.persona)

        touch_count = await db.scalar(
            select(func.count(Touch.id)).where(Touch.lead_id == lead.id)
        ) or 0
        if touch_count >= rule["max_touches"]:
            continue

        last_touch_at = await db.scalar(
            select(func.max(Touch.created_at)).where(Touch.lead_id == lead.id)
        )
        if last_touch_at is not None:
            spacing = timedelta(days=rule["touch_spacing_days"])
            if now - last_touch_at < spacing:
                continue

        eligible.append(lead)
        if len(eligible) >= limit:
            break
    return eligible


async def _process_lead(db, lead: Lead) -> bool:
    """Generate + push one lead. Returns True on success, False if skipped or
    if the send failed (caller should rollback the session).

    Honors the REQUIRE_APPROVAL setting: when on, the scheduler still generates
    the draft and writes a pending Touch, but doesn't send. The human approves
    from the dashboard.
    """
    try:
        await assert_safe_to_send(db, lead.domain or "")
    except SafetyViolation as e:
        log.warning("safety: skipping %s: %s", lead.email, e)
        return False

    require_approval = (await app_settings.get(db, "REQUIRE_APPROVAL") or "").lower() in ("1", "true", "yes")

    policy = await decide_policy(db, lead)
    message = await generate_email(lead, policy)

    touch = Touch(
        lead_id=lead.id,
        channel=policy.channel,
        angle=policy.angle,
        template_family=policy.template_family,
        subject=message["subject"],
        body=message["body"],
        scheduled_at=datetime.now(timezone.utc),
        status="pending_approval" if require_approval else "approved",
    )
    db.add(touch)
    await db.flush()

    if require_approval:
        log.info("queued PENDING APPROVAL lead=%s ch=%s angle=%s",
                 lead.email, policy.channel, policy.angle)
        return True

    if policy.channel == "email":
        try:
            await send_message(
                db=db,
                email=lead.email,
                first_name=lead.first_name,
                last_name=lead.last_name,
                company=lead.company,
                template_family=policy.template_family,
                subject=message["subject"],
                body=message["body"],
            )
        except Exception:
            log.exception("send failed for %s; rolling back touch", lead.email)
            return False

    log.info("queued touch lead=%s ch=%s angle=%s",
             lead.email, policy.channel, policy.angle)
    return True


async def tick() -> None:
    """One pass: find eligible leads (one read session), then process each in
    its own write session so a failure on one lead doesn't roll back the rest.
    Skips entirely when outside the configured send window."""
    async with AsyncSessionLocal() as discovery_db:
        days = await app_settings.get(discovery_db, "SCHEDULER_SEND_DAYS")
        sh   = await app_settings.get(discovery_db, "SCHEDULER_START_HOUR")
        eh   = await app_settings.get(discovery_db, "SCHEDULER_END_HOUR")
        tz   = await app_settings.get(discovery_db, "SCHEDULER_TIMEZONE")
        if not is_in_send_window(datetime.now(timezone.utc), days, sh, eh, tz):
            log.info("tick skipped: outside send window")
            return
        leads = await _find_eligible_leads(
            discovery_db, limit=settings.SCHEDULER_BATCH_SIZE
        )
    log.info("tick: %d eligible leads", len(leads))

    for lead in leads:
        async with AsyncSessionLocal() as work_db:
            try:
                ok = await _process_lead(work_db, lead)
                if ok:
                    await work_db.commit()
                else:
                    await work_db.rollback()
            except Exception:
                await work_db.rollback()
                log.exception("unhandled error processing %s", lead.email)


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    if not settings.SCHEDULER_ENABLED:
        log.info("scheduler disabled (SCHEDULER_ENABLED=false)")
        return
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        tick,
        "interval",
        minutes=settings.SCHEDULER_INTERVAL_MINUTES,
        id="outreach_tick",
        replace_existing=True,
        max_instances=1,  # don't overlap if a tick takes longer than the interval
    )
    _scheduler.start()
    log.info("scheduler started: every %dm, batch=%d",
             settings.SCHEDULER_INTERVAL_MINUTES, settings.SCHEDULER_BATCH_SIZE)


def stop() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
