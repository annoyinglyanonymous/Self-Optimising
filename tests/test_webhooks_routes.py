"""Tests for POST /webhooks/instantly. Skip unless TEST_DATABASE_URL is set.

Lower-level idempotency / reward tests live in test_webhook_idempotency.py and
test_reward_recording.py — these exercise the route boundary itself.
"""
import uuid

import pytest
from sqlalchemy import select

from app.models import Event, Lead, PolicyStat, Touch
from app.services.bandit import make_segment_key


@pytest.fixture
def fixed_classifier(monkeypatch):
    """Pin the LLM-backed reply classifier to a deterministic label."""
    label_holder = {"label": "positive"}

    async def fake_classify(reply_text, original_subject=None, persona=None):
        return {"label": label_holder["label"], "confidence": 0.99, "reasoning": "test"}

    from app.routers import webhooks
    monkeypatch.setattr(webhooks, "classify_reply", fake_classify)
    return label_holder


async def _seed_lead_with_email_touch(db_session, persona="insurance_agent"):
    lead = Lead(
        id=uuid.uuid4(),
        email=f"wh-{uuid.uuid4().hex[:8]}@example.com",
        domain="example.com",
        persona=persona,
        enrichment_status="complete",
    )
    touch = Touch(
        id=uuid.uuid4(),
        lead_id=lead.id,
        channel="email",
        angle="pain",
        template_family=f"{persona}_pain_v1",
    )
    db_session.add(lead)
    db_session.add(touch)
    await db_session.commit()
    await db_session.refresh(lead)
    await db_session.refresh(touch)
    return lead, touch


async def test_unknown_event_type_is_ignored(client, db_session):
    lead, _ = await _seed_lead_with_email_touch(db_session)

    r = await client.post("/webhooks/instantly", json={
        "event_type": "something_we_dont_handle",
        "lead_email": lead.email,
    })
    assert r.status_code == 200
    assert r.json() == {"status": "ignored", "reason": "unknown_event_type"}

    events = (await db_session.execute(select(Event).where(Event.lead_id == lead.id))).scalars().all()
    assert events == []


async def test_payload_without_email_is_ignored(client):
    r = await client.post("/webhooks/instantly", json={"event_type": "email_opened"})
    assert r.status_code == 200
    assert r.json() == {"status": "ignored", "reason": "no_email"}


async def test_unknown_lead_email_is_ignored(client):
    r = await client.post("/webhooks/instantly", json={
        "event_type": "email_opened",
        "lead_email": "ghost@example.com",
    })
    assert r.status_code == 200
    assert r.json() == {"status": "ignored", "reason": "lead_not_found"}


async def test_open_event_writes_event_and_credits_bandit(client, db_session):
    lead, touch = await _seed_lead_with_email_touch(db_session)

    r = await client.post("/webhooks/instantly", json={
        "event_type": "email_opened",
        "lead_email": lead.email,
    })
    assert r.status_code == 200
    assert r.json()["event_type"] == "email_opened"

    events = (await db_session.execute(
        select(Event).where(Event.lead_id == lead.id)
    )).scalars().all()
    assert [e.event_type for e in events] == ["email_opened"]

    stat = (await db_session.execute(
        select(PolicyStat).where(
            PolicyStat.segment_key == make_segment_key(lead.persona, "email", "pain")
        )
    )).scalar_one()
    assert stat.trials == 1


async def test_classified_reply_writes_two_events(client, db_session, fixed_classifier):
    lead, touch = await _seed_lead_with_email_touch(db_session)

    r = await client.post("/webhooks/instantly", json={
        "event_type": "email_replied",
        "lead_email": lead.email,
        "reply_text": "Yes I'd love to chat",
    })

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["classified_as"] == "positive"

    events = (await db_session.execute(
        select(Event).where(Event.lead_id == lead.id).order_by(Event.created_at.asc())
    )).scalars().all()
    types = [e.event_type for e in events]
    assert "reply_received" in types
    assert "reply_classified_positive" in types
