"""Tests for /api/dashboard/* routes. Skip unless TEST_DATABASE_URL is set."""
import uuid

from app.models import Event, Lead, PolicyStat, Touch


async def _seed_minimal_activity(db_session):
    lead = Lead(
        id=uuid.uuid4(),
        email=f"dash-{uuid.uuid4().hex[:8]}@example.com",
        domain="example.com",
        persona="insurance_agent",
        company="Acme",
        enrichment_status="complete",
    )
    touch = Touch(
        id=uuid.uuid4(), lead_id=lead.id, channel="email", angle="pain",
    )
    db_session.add_all([lead, touch])
    await db_session.commit()
    await db_session.refresh(lead)
    await db_session.refresh(touch)

    # 10 sent, 5 opened, 1 positive reply.
    for _ in range(10):
        db_session.add(Event(lead_id=lead.id, touch_id=touch.id, event_type="email_sent"))
    for _ in range(5):
        db_session.add(Event(lead_id=lead.id, touch_id=touch.id, event_type="email_opened"))
    db_session.add(Event(
        lead_id=lead.id, touch_id=touch.id, event_type="reply_classified_positive",
    ))
    await db_session.commit()
    return lead, touch


async def test_stats_returns_aggregates_and_rates(client, db_session):
    await _seed_minimal_activity(db_session)

    r = await client.get("/api/dashboard/stats?days=30")

    assert r.status_code == 200
    body = r.json()
    assert body["window_days"] == 30
    assert body["total_leads"] == 1
    assert body["events"]["sent"] == 10
    assert body["events"]["opened"] == 5
    assert body["events"]["positive"] == 1
    assert body["rates"]["open_rate"] == 0.5
    assert body["rates"]["positive_rate"] == 0.1


async def test_stats_window_clamps_param(client):
    # ge=1, le=365 — out-of-range should be 422.
    assert (await client.get("/api/dashboard/stats?days=0")).status_code == 422
    assert (await client.get("/api/dashboard/stats?days=10000")).status_code == 422


async def test_stats_requires_auth_when_enabled(client, monkeypatch):
    from app.config import settings as app_settings
    monkeypatch.setattr(app_settings, "AUTH_REQUIRED", True)

    r = await client.get("/api/dashboard/stats")
    assert r.status_code == 401


async def test_leads_list_supports_search_and_persona_filter(client, db_session):
    db_session.add_all([
        Lead(email="acme-a@example.com", company="Acme", persona="insurance_agent", enrichment_status="complete"),
        Lead(email="other@example.com", company="Other", persona="default", enrichment_status="complete"),
    ])
    await db_session.commit()

    r = await client.get("/api/dashboard/leads?persona=insurance_agent")
    assert r.status_code == 200
    items = r.json()["items"]
    assert {l["email"] for l in items} == {"acme-a@example.com"}

    r = await client.get("/api/dashboard/leads?search=acme")
    items = r.json()["items"]
    assert {l["email"] for l in items} == {"acme-a@example.com"}


async def test_lead_detail_returns_touches_and_events(client, db_session):
    lead, touch = await _seed_minimal_activity(db_session)

    r = await client.get(f"/api/dashboard/leads/{lead.id}")

    assert r.status_code == 200
    body = r.json()
    assert body["lead"]["email"] == lead.email
    assert len(body["touches"]) == 1
    # 16 events seeded.
    assert len(body["events"]) == 16


async def test_lead_detail_unknown_id_is_404(client):
    r = await client.get(f"/api/dashboard/leads/{uuid.uuid4()}")
    assert r.status_code == 404


async def test_policy_stats_route(client, db_session):
    db_session.add(PolicyStat(
        segment_key="insurance_agent|email|pain",
        persona="insurance_agent",
        channel="email",
        angle="pain",
        trials=20,
        successes=4.0,
        alpha=5.0,
        beta_param=17.0,
    ))
    await db_session.commit()

    r = await client.get("/api/dashboard/policy-stats")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    row = items[0]
    assert row["segment_key"] == "insurance_agent|email|pain"
    assert row["trials"] == 20
    assert 0.0 < row["posterior_mean"] < 1.0


async def test_activity_route(client, db_session):
    await _seed_minimal_activity(db_session)
    r = await client.get("/api/dashboard/activity?limit=5")
    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 5
    assert all("event_type" in item for item in items)


async def test_personas_route(client, db_session):
    db_session.add_all([
        Lead(email="p1@example.com", persona="insurance_agent", enrichment_status="complete"),
        Lead(email="p2@example.com", persona="insurance_agent", enrichment_status="complete"),
        Lead(email="p3@example.com", persona="insurance_agency_owner", enrichment_status="complete"),
    ])
    await db_session.commit()

    r = await client.get("/api/dashboard/personas")
    items = r.json()["items"]
    counts = {i["persona"]: i["count"] for i in items}
    assert counts == {"insurance_agent": 2, "insurance_agency_owner": 1}
