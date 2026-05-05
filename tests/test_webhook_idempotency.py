"""DB-backed test for webhook retry idempotency.

The bandit must NOT be double-credited when Instantly retries a webhook.
See _credit_bandit in app/routers/webhooks.py.

Skipped unless TEST_DATABASE_URL is set.
"""
import uuid

import pytest
from sqlalchemy import select

from app.models import Lead, Touch, Event, PolicyStat
from app.routers.webhooks import _credit_bandit
from app.services.bandit import make_segment_key


pytestmark = pytest.mark.asyncio


async def _seed_lead_and_touch(db, persona: str = "insurance_agent"):
    suffix = uuid.uuid4().hex[:8]
    lead = Lead(
        id=uuid.uuid4(),
        email=f"test-{suffix}@example.com",
        persona=persona,
        domain="example.com",
        enrichment_status="complete",
    )
    touch = Touch(
        id=uuid.uuid4(),
        lead_id=lead.id,
        channel="email",
        angle="pain",
        template_family=f"{persona}_pain_v1",
    )
    db.add(lead)
    db.add(touch)
    await db.flush()
    return lead, touch


async def test_first_event_credits_bandit(db_session):
    lead, touch = await _seed_lead_and_touch(db_session)

    db_session.add(Event(
        id=uuid.uuid4(),
        lead_id=lead.id,
        touch_id=touch.id,
        event_type="reply_classified_positive",
        channel="email",
    ))
    await db_session.flush()
    await _credit_bandit(db_session, lead, touch, "reply_classified_positive")

    stat = (await db_session.execute(
        select(PolicyStat).where(
            PolicyStat.segment_key == make_segment_key(lead.persona, "email", "pain")
        )
    )).scalar_one()
    assert stat.trials == 1


async def test_duplicate_event_does_not_double_credit(db_session):
    """Simulate Instantly retrying the same webhook: two events of the same
    type are written for the same touch. _credit_bandit should only credit on
    the first."""
    lead, touch = await _seed_lead_and_touch(db_session)

    # First webhook delivery
    db_session.add(Event(
        id=uuid.uuid4(),
        lead_id=lead.id,
        touch_id=touch.id,
        event_type="bounce",
        channel="email",
    ))
    await db_session.flush()
    await _credit_bandit(db_session, lead, touch, "bounce")

    # Retry — same event_type, same touch
    db_session.add(Event(
        id=uuid.uuid4(),
        lead_id=lead.id,
        touch_id=touch.id,
        event_type="bounce",
        channel="email",
    ))
    await db_session.flush()
    await _credit_bandit(db_session, lead, touch, "bounce")

    stat = (await db_session.execute(
        select(PolicyStat).where(
            PolicyStat.segment_key == make_segment_key(lead.persona, "email", "pain")
        )
    )).scalar_one()
    assert stat.trials == 1, "duplicate webhook should not have inflated trials"


async def test_no_persona_skips_credit(db_session):
    """Without a persona we can't construct a segment_key — _credit_bandit
    must bail rather than crash."""
    suffix = uuid.uuid4().hex[:8]
    lead = Lead(
        id=uuid.uuid4(),
        email=f"no-persona-{suffix}@example.com",
        persona=None,
        domain="example.com",
        enrichment_status="complete",
    )
    touch = Touch(
        id=uuid.uuid4(),
        lead_id=lead.id,
        channel="email",
        angle="pain",
    )
    db_session.add(lead)
    db_session.add(touch)
    await db_session.flush()

    db_session.add(Event(
        id=uuid.uuid4(),
        lead_id=lead.id,
        touch_id=touch.id,
        event_type="reply_classified_positive",
    ))
    await db_session.flush()

    # Should not raise.
    await _credit_bandit(db_session, lead, touch, "reply_classified_positive")

    # No PolicyStat row should have been created.
    rows = (await db_session.execute(select(PolicyStat))).scalars().all()
    assert all(r.persona != lead.persona for r in rows)
