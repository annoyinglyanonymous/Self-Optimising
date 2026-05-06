"""Tests for PATCH /leads/{id}. Skip unless TEST_DATABASE_URL is set."""
import uuid

from sqlalchemy import select

from app.models import Lead


async def _seed_lead(db_session, **overrides) -> Lead:
    lead = Lead(
        id=uuid.uuid4(),
        email=overrides.pop("email", f"seed-{uuid.uuid4().hex[:8]}@example.com"),
        enrichment_status="pending",
        **overrides,
    )
    db_session.add(lead)
    await db_session.commit()
    await db_session.refresh(lead)
    return lead


async def test_patch_updates_supplied_fields_only(client, db_session):
    lead = await _seed_lead(db_session, first_name="Alex", company="Old Co")

    r = await client.patch(f"/leads/{lead.id}", json={"company": "New Co"})

    assert r.status_code == 200, r.text
    refreshed = (await db_session.execute(
        select(Lead).where(Lead.id == lead.id)
    )).scalar_one()
    await db_session.refresh(refreshed)
    assert refreshed.company == "New Co"
    assert refreshed.first_name == "Alex"  # untouched


async def test_patch_invalid_enrichment_status_is_400(client, db_session):
    lead = await _seed_lead(db_session)
    r = await client.patch(f"/leads/{lead.id}", json={"enrichment_status": "bogus"})
    assert r.status_code == 400


async def test_patch_email_collision_returns_409(client, db_session):
    a = await _seed_lead(db_session, email="a@example.com")
    await _seed_lead(db_session, email="b@example.com")

    r = await client.patch(f"/leads/{a.id}", json={"email": "b@example.com"})

    assert r.status_code == 409
    assert "already used" in r.json()["detail"]


async def test_patch_unknown_id_is_404(client):
    r = await client.patch(f"/leads/{uuid.uuid4()}", json={"company": "Whatever"})
    assert r.status_code == 404


async def test_patch_email_lowercases_and_keeps_id_stable(client, db_session):
    lead = await _seed_lead(db_session, email="old@example.com")

    r = await client.patch(f"/leads/{lead.id}", json={"email": "NEW@Example.com"})

    assert r.status_code == 200
    assert r.json()["email"] == "new@example.com"
    refreshed = (await db_session.execute(
        select(Lead).where(Lead.id == lead.id)
    )).scalar_one()
    await db_session.refresh(refreshed)
    assert refreshed.email == "new@example.com"
