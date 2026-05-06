"""Tests for POST /leads/{id}/generate. Skip unless TEST_DATABASE_URL is set.

Mocks the OpenAI-backed message generator and the sender so tests run offline.
"""
import uuid
from datetime import datetime, timezone, timedelta

import pytest
from sqlalchemy import select

from app.models import AccountSuppression, Lead, Setting, Touch


_FAKE_MESSAGE = {"subject": "Hello", "body": "Just testing"}


@pytest.fixture
def mock_generate_and_send(monkeypatch):
    """Replace the message generator and sender with deterministic stubs."""
    sent: list[dict] = []

    async def fake_generate(lead, policy):
        return dict(_FAKE_MESSAGE)

    async def fake_send(**kwargs):
        sent.append(kwargs)
        return "fake-send-ref"

    from app.routers import leads as leads_router
    monkeypatch.setattr(leads_router, "generate_email", fake_generate)
    monkeypatch.setattr(leads_router, "send_message", fake_send)
    return sent


async def _seed_lead(db_session, **overrides) -> Lead:
    lead = Lead(
        id=uuid.uuid4(),
        email=overrides.pop("email", f"gen-{uuid.uuid4().hex[:8]}@example.com"),
        domain=overrides.pop("domain", "example.com"),
        persona=overrides.pop("persona", "insurance_agent"),
        enrichment_status="complete",
        **overrides,
    )
    db_session.add(lead)
    await db_session.commit()
    await db_session.refresh(lead)
    return lead


async def test_generate_auto_approved_writes_touch_and_sends(client, db_session, mock_generate_and_send):
    lead = await _seed_lead(db_session)

    r = await client.post(f"/leads/{lead.id}/generate")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved"
    assert body["send_ref"] == "fake-send-ref"
    assert body["message"] == _FAKE_MESSAGE
    assert body["policy"]["channel"] == "email"  # only channel left in AVAILABLE_CHANNELS

    assert len(mock_generate_and_send) == 1
    assert mock_generate_and_send[0]["email"] == lead.email

    touches = (await db_session.execute(
        select(Touch).where(Touch.lead_id == lead.id)
    )).scalars().all()
    assert len(touches) == 1
    assert touches[0].status == "approved"
    assert touches[0].decided_at is not None


async def test_generate_with_require_approval_returns_pending_and_does_not_send(
    client, db_session, mock_generate_and_send,
):
    db_session.add(Setting(key="REQUIRE_APPROVAL", value="true", is_secret=False))
    await db_session.commit()

    lead = await _seed_lead(db_session)

    r = await client.post(f"/leads/{lead.id}/generate")

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "pending_approval"
    assert body["send_ref"] == ""
    assert mock_generate_and_send == []  # never sent

    touches = (await db_session.execute(
        select(Touch).where(Touch.lead_id == lead.id)
    )).scalars().all()
    assert len(touches) == 1
    assert touches[0].status == "pending_approval"
    assert touches[0].decided_at is None


async def test_generate_unknown_lead_is_404(client, mock_generate_and_send):
    r = await client.post(f"/leads/{uuid.uuid4()}/generate")
    assert r.status_code == 404


async def test_generate_blocked_by_domain_suppression_returns_423(
    client, db_session, mock_generate_and_send,
):
    lead = await _seed_lead(db_session, domain="blocked.example")
    db_session.add(AccountSuppression(domain="blocked.example", reason="manual"))
    await db_session.commit()

    r = await client.post(f"/leads/{lead.id}/generate")

    assert r.status_code == 423
    assert "suppressed" in r.json()["detail"].lower()
    # No touch row created.
    touches = (await db_session.execute(
        select(Touch).where(Touch.lead_id == lead.id)
    )).scalars().all()
    assert touches == []


async def test_generate_send_failure_returns_502(client, db_session, monkeypatch):
    lead = await _seed_lead(db_session)

    async def fake_generate(lead, policy):
        return dict(_FAKE_MESSAGE)

    async def failing_send(**kwargs):
        raise RuntimeError("smtp blew up")

    from app.routers import leads as leads_router
    monkeypatch.setattr(leads_router, "generate_email", fake_generate)
    monkeypatch.setattr(leads_router, "send_message", failing_send)

    r = await client.post(f"/leads/{lead.id}/generate")

    assert r.status_code == 502
    assert "smtp blew up" in r.json()["detail"]


async def test_expired_suppression_does_not_block_send(
    client, db_session, mock_generate_and_send,
):
    """Suppression with `expires_at` in the past should not block."""
    lead = await _seed_lead(db_session, domain="ex-suppressed.example")
    db_session.add(AccountSuppression(
        domain="ex-suppressed.example",
        reason="bounced",
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    ))
    await db_session.commit()

    r = await client.post(f"/leads/{lead.id}/generate")
    assert r.status_code == 200, r.text
