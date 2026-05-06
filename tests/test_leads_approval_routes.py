"""Tests for the approval workflow routes:
GET  /leads/touches/pending
PATCH /leads/touches/{id}
POST  /leads/touches/{id}/approve
POST  /leads/touches/{id}/reject

Skip unless TEST_DATABASE_URL is set.
"""
import uuid

import pytest
from sqlalchemy import select

from app.models import Lead, Touch


@pytest.fixture
def mock_sender(monkeypatch):
    sent: list[dict] = []

    async def fake_send(**kwargs):
        sent.append(kwargs)
        return "fake-send-ref"

    from app.routers import leads as leads_router
    monkeypatch.setattr(leads_router, "send_message", fake_send)
    return sent


async def _seed_pending(db_session, **lead_overrides) -> tuple[Lead, Touch]:
    lead = Lead(
        id=uuid.uuid4(),
        email=lead_overrides.pop("email", f"approver-{uuid.uuid4().hex[:8]}@example.com"),
        domain=lead_overrides.pop("domain", "example.com"),
        persona=lead_overrides.pop("persona", "insurance_agent"),
        enrichment_status="complete",
        **lead_overrides,
    )
    touch = Touch(
        id=uuid.uuid4(),
        lead_id=lead.id,
        channel="email",
        angle="pain",
        template_family="insurance_agent_pain_v1",
        subject="Original subject",
        body="Original body",
        status="pending_approval",
    )
    db_session.add(lead)
    db_session.add(touch)
    await db_session.commit()
    await db_session.refresh(lead)
    await db_session.refresh(touch)
    return lead, touch


async def test_list_pending_returns_lead_context(client, db_session):
    lead, touch = await _seed_pending(db_session, first_name="Pat", company="Acme", title="Agent")

    r = await client.get("/leads/touches/pending")

    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["touch_id"] == str(touch.id)
    assert item["lead"]["email"] == lead.email
    assert item["lead"]["company"] == "Acme"
    assert item["subject"] == "Original subject"


async def test_list_pending_excludes_approved_and_rejected(client, db_session):
    lead, _pending = await _seed_pending(db_session)
    # Add an approved + rejected touch on the same lead.
    db_session.add(Touch(
        id=uuid.uuid4(), lead_id=lead.id, channel="email", angle="pain", status="approved",
    ))
    db_session.add(Touch(
        id=uuid.uuid4(), lead_id=lead.id, channel="email", angle="pain", status="rejected",
    ))
    await db_session.commit()

    r = await client.get("/leads/touches/pending")
    assert r.status_code == 200
    assert len(r.json()["items"]) == 1


async def test_patch_pending_updates_subject_and_body(client, db_session):
    _lead, touch = await _seed_pending(db_session)

    r = await client.patch(f"/leads/touches/{touch.id}", json={"subject": "New", "body": "New body"})

    assert r.status_code == 200, r.text
    refreshed = (await db_session.execute(select(Touch).where(Touch.id == touch.id))).scalar_one()
    await db_session.refresh(refreshed)
    assert refreshed.subject == "New"
    assert refreshed.body == "New body"


async def test_patch_non_pending_is_409(client, db_session):
    _lead, touch = await _seed_pending(db_session)
    touch.status = "approved"
    await db_session.commit()

    r = await client.patch(f"/leads/touches/{touch.id}", json={"subject": "Too late"})
    assert r.status_code == 409


async def test_approve_sends_and_marks_approved(client, db_session, mock_sender):
    _lead, touch = await _seed_pending(db_session)

    r = await client.post(f"/leads/touches/{touch.id}/approve", json={})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved"
    assert body["send_ref"] == "fake-send-ref"
    assert len(mock_sender) == 1
    # The sender was given the original subject/body.
    assert mock_sender[0]["subject"] == "Original subject"

    refreshed = (await db_session.execute(select(Touch).where(Touch.id == touch.id))).scalar_one()
    await db_session.refresh(refreshed)
    assert refreshed.status == "approved"
    assert refreshed.decided_at is not None


async def test_approve_with_last_minute_edits_uses_new_text(client, db_session, mock_sender):
    _lead, touch = await _seed_pending(db_session)

    r = await client.post(
        f"/leads/touches/{touch.id}/approve",
        json={"subject": "Edited subject", "body": "Edited body"},
    )

    assert r.status_code == 200
    assert mock_sender[0]["subject"] == "Edited subject"
    assert mock_sender[0]["body"] == "Edited body"


async def test_approve_when_not_pending_is_409(client, db_session, mock_sender):
    _lead, touch = await _seed_pending(db_session)
    touch.status = "approved"
    await db_session.commit()

    r = await client.post(f"/leads/touches/{touch.id}/approve", json={})
    assert r.status_code == 409
    assert mock_sender == []  # never sent


async def test_approve_send_failure_keeps_touch_pending(client, db_session, monkeypatch):
    _lead, touch = await _seed_pending(db_session)

    async def failing_send(**kwargs):
        raise RuntimeError("kaboom")

    from app.routers import leads as leads_router
    monkeypatch.setattr(leads_router, "send_message", failing_send)

    r = await client.post(f"/leads/touches/{touch.id}/approve", json={})

    assert r.status_code == 502
    refreshed = (await db_session.execute(select(Touch).where(Touch.id == touch.id))).scalar_one()
    await db_session.refresh(refreshed)
    assert refreshed.status == "pending_approval", "user should be able to retry"


async def test_reject_marks_rejected(client, db_session):
    _lead, touch = await _seed_pending(db_session)

    r = await client.post(f"/leads/touches/{touch.id}/reject")

    assert r.status_code == 200
    refreshed = (await db_session.execute(select(Touch).where(Touch.id == touch.id))).scalar_one()
    await db_session.refresh(refreshed)
    assert refreshed.status == "rejected"
    assert refreshed.decided_at is not None


async def test_reject_when_not_pending_is_409(client, db_session):
    _lead, touch = await _seed_pending(db_session)
    touch.status = "rejected"
    await db_session.commit()

    r = await client.post(f"/leads/touches/{touch.id}/reject")
    assert r.status_code == 409


async def test_unknown_touch_returns_404(client):
    bogus = uuid.uuid4()
    assert (await client.patch(f"/leads/touches/{bogus}", json={"subject": "x"})).status_code == 404
    assert (await client.post(f"/leads/touches/{bogus}/approve", json={})).status_code == 404
    assert (await client.post(f"/leads/touches/{bogus}/reject")).status_code == 404
