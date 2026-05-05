from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from app.database import get_db
from app.models import Lead, Touch, Event
from app.services.classifier import classify_reply, label_to_event_type
from app.services.bandit import record_reward

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

INSTANTLY_MAP = {
    "email_sent":         "email_sent",
    "email_opened":       "email_opened",
    "email_clicked":      "email_clicked",
    "email_replied":      "reply_received",
    "email_bounced":      "bounce",
    "email_unsubscribed": "unsubscribe",
    "spam_complaint":     "spam_complaint",
}

# Reward signal per event type. Tuned so a positive reply dominates a few
# bounces, and unsubscribe / spam are strongly penalized. Events not listed
# here are not credited to the bandit.
EVENT_REWARDS: dict[str, float] = {
    "reply_classified_positive":     10.0,
    "reply_classified_objection":    -2.0,
    "reply_classified_unsubscribe": -10.0,
    "reply_classified_wrong_contact": -1.0,
    "reply_classified_ooo":           0.0,
    "bounce":                        -5.0,
    "spam_complaint":               -10.0,
    "email_clicked":                  0.5,
    "email_opened":                   0.1,
}


async def _credit_bandit(
    db: AsyncSession,
    lead: Lead,
    touch: Touch | None,
    event_type: str,
) -> None:
    """Update PolicyStat for the segment that produced this touch, if known.

    Idempotent against webhook retries: if an event of this type already
    exists for this touch (other than the one we just inserted), skip the
    reward to avoid inflating bandit trials.
    """
    reward = EVENT_REWARDS.get(event_type)
    if reward is None or touch is None or not lead.persona:
        return
    count = await db.scalar(
        select(func.count(Event.id)).where(
            Event.touch_id == touch.id,
            Event.event_type == event_type,
        )
    )
    if count and count > 1:
        return
    await record_reward(
        db=db,
        persona=lead.persona,
        channel=touch.channel,
        angle=touch.angle,
        reward=reward,
    )

class InstantlyEvent(BaseModel):
    event_type: str
    lead_email: str | None = None
    email: str | None = None
    campaign_id: str | None = None
    reply_text: str | None = None
    subject: str | None = None

@router.post("/instantly")
async def instantly_webhook(
    payload: InstantlyEvent,
    db: AsyncSession = Depends(get_db)
):
    lead_email = payload.lead_email or payload.email
    if not lead_email:
        return {"status": "ignored", "reason": "no_email"}

    result = await db.execute(
        select(Lead).where(Lead.email == lead_email)
    )
    lead = result.scalar_one_or_none()
    if not lead:
        return {"status": "ignored", "reason": "lead_not_found"}

    event_type = INSTANTLY_MAP.get(payload.event_type)
    if not event_type:
        return {"status": "ignored", "reason": "unknown_event_type"}

    touch_result = await db.execute(
        select(Touch)
        .where(Touch.lead_id == lead.id, Touch.channel == "email")
        .order_by(Touch.created_at.desc())
        .limit(1)
    )
    touch = touch_result.scalar_one_or_none()

    if event_type == "reply_received" and payload.reply_text:
        classification = await classify_reply(
            reply_text=payload.reply_text,
            original_subject=payload.subject,
            persona=lead.persona,
        )
        classified_event_type = label_to_event_type(classification["label"])

        db.add(Event(
            lead_id=lead.id,
            touch_id=touch.id if touch else None,
            event_type="reply_received",
            channel="email",
        ))
        db.add(Event(
            lead_id=lead.id,
            touch_id=touch.id if touch else None,
            event_type=classified_event_type,
            channel="email",
        ))
        await db.flush()
        await _credit_bandit(db, lead, touch, classified_event_type)
        return {"status": "ok", "classified_as": classification["label"]}

    event = Event(
        lead_id=lead.id,
        touch_id=touch.id if touch else None,
        event_type=event_type,
        channel="email",
    )
    db.add(event)
    await db.flush()
    await _credit_bandit(db, lead, touch, event_type)

    return {"status": "ok", "event_type": event_type}