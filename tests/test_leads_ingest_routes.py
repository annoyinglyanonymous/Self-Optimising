"""Tests for POST /leads/ingest. Skip unless TEST_DATABASE_URL is set."""
from sqlalchemy import select

from app.models import Event, Lead


async def test_ingest_creates_new_lead_with_default_status(client, db_session):
    r = await client.post("/leads/ingest", json={
        "email": "alex@example.com",
        "first_name": "Alex",
        "company": "Acme",
        "persona": "insurance_agent",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["email"] == "alex@example.com"

    lead = (await db_session.execute(
        select(Lead).where(Lead.email == "alex@example.com")
    )).scalar_one()
    assert lead.first_name == "Alex"
    assert lead.persona == "insurance_agent"
    # Default status when none supplied.
    assert lead.enrichment_status == "complete"

    events = (await db_session.execute(
        select(Event).where(Event.lead_id == lead.id)
    )).scalars().all()
    assert [e.event_type for e in events] == ["lead_created"]


async def test_ingest_existing_email_upserts_and_writes_enrichment_event(client, db_session):
    # First call: create.
    r1 = await client.post("/leads/ingest", json={"email": "x@example.com", "company": "Old"})
    assert r1.status_code == 200

    # Second call with new field values: should update, not insert.
    r2 = await client.post("/leads/ingest", json={"email": "x@example.com", "company": "New", "title": "VP"})
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]

    leads = (await db_session.execute(select(Lead).where(Lead.email == "x@example.com"))).scalars().all()
    assert len(leads) == 1
    assert leads[0].company == "New"
    assert leads[0].title == "VP"

    events = (await db_session.execute(
        select(Event).where(Event.lead_id == leads[0].id).order_by(Event.created_at.asc())
    )).scalars().all()
    assert [e.event_type for e in events] == ["lead_created", "enrichment_completed"]


async def test_ingest_invalid_enrichment_status_is_400(client):
    r = await client.post("/leads/ingest", json={
        "email": "y@example.com",
        "enrichment_status": "definitely-not-valid",
    })
    assert r.status_code == 400
    assert "enrichment_status" in r.json()["detail"]


async def test_ingest_supplied_enrichment_status_is_respected(client, db_session):
    r = await client.post("/leads/ingest", json={
        "email": "p@example.com",
        "enrichment_status": "in_progress",
    })
    assert r.status_code == 200
    lead = (await db_session.execute(
        select(Lead).where(Lead.email == "p@example.com")
    )).scalar_one()
    assert lead.enrichment_status == "in_progress"
