"""Tests for POST /leads/import-csv and the template download.
Skip unless TEST_DATABASE_URL is set.

Pure parsing of CSV rows is covered by test_csv_import_pure.py — these tests
focus on the route boundary: error responses, batched upsert, event writing.
"""
from sqlalchemy import select

from app.models import Event, Lead


def _csv(*rows: str) -> bytes:
    header = (
        "email,first_name,last_name,company,domain,title,linkedin_url,persona,"
        "company_size,state,growth_stage,tech_stack\n"
    )
    return (header + "\n".join(rows) + "\n").encode("utf-8")


async def test_template_endpoint_returns_csv(client):
    r = await client.get("/leads/import-csv/template")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "email" in r.text
    assert "tech_stack" in r.text


async def test_clean_csv_creates_all_rows(client, db_session):
    body = _csv(
        "alex@example.com,Alex,,Acme,acme.example,Agent,,insurance_agent,11-50,CA,growth,",
        "ben@example.com,Ben,,Beta,beta.example,Owner,,insurance_agency_owner,1-10,NY,startup,",
    )

    r = await client.post("/leads/import-csv", files={"file": ("leads.csv", body, "text/csv")})

    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_rows"] == 2
    assert data["created"] == 2
    assert data["updated"] == 0
    assert data["errors"] == []

    leads = (await db_session.execute(select(Lead))).scalars().all()
    assert {l.email for l in leads} == {"alex@example.com", "ben@example.com"}

    # One lead_created event per new lead.
    events = (await db_session.execute(
        select(Event).where(Event.event_type == "lead_created")
    )).scalars().all()
    assert len(events) == 2


async def test_csv_with_invalid_emails_reports_per_row_errors(client, db_session):
    body = _csv(
        "good@example.com,Good,,,,,,,,,,",
        ",NoEmail,,,,,,,,,,",
        "bad-email,BadFormat,,,,,,,,,,",
    )

    r = await client.post("/leads/import-csv", files={"file": ("leads.csv", body, "text/csv")})

    assert r.status_code == 200
    data = r.json()
    assert data["created"] == 1
    assert {e["row"] for e in data["errors"]} == {3, 4}
    reasons = {e["reason"] for e in data["errors"]}
    assert "missing email" in reasons
    assert "invalid email format" in reasons


async def test_csv_duplicate_email_in_file_keeps_first(client, db_session):
    body = _csv(
        "dup@example.com,First,,Co1,,,,,,,,",
        "dup@example.com,Second,,Co2,,,,,,,,",
    )

    r = await client.post("/leads/import-csv", files={"file": ("leads.csv", body, "text/csv")})

    assert r.status_code == 200
    data = r.json()
    assert data["created"] == 1
    assert any(e["reason"] == "duplicate email in file" for e in data["errors"])

    lead = (await db_session.execute(
        select(Lead).where(Lead.email == "dup@example.com")
    )).scalar_one()
    assert lead.first_name == "First"  # first wins; second is dropped


async def test_csv_upsert_updates_existing_lead(client, db_session):
    db_session.add(Lead(email="upd@example.com", first_name="Old", enrichment_status="pending"))
    await db_session.commit()

    body = _csv("upd@example.com,New,,NewCo,,,,,,,,")

    r = await client.post("/leads/import-csv", files={"file": ("leads.csv", body, "text/csv")})

    data = r.json()
    assert data["created"] == 0
    assert data["updated"] == 1

    refreshed = (await db_session.execute(
        select(Lead).where(Lead.email == "upd@example.com")
    )).scalar_one()
    await db_session.refresh(refreshed)
    assert refreshed.first_name == "New"
    assert refreshed.company == "NewCo"


async def test_non_utf8_file_is_400(client):
    # 0xFF is invalid UTF-8.
    r = await client.post("/leads/import-csv", files={"file": ("bad.csv", b"\xff\xfe\xff\xfe", "text/csv")})
    assert r.status_code == 400
    assert "UTF-8" in r.json()["detail"]


async def test_oversized_byte_count_is_413(client, monkeypatch):
    # Push the limit way down so the test stays fast.
    from app.routers import leads as leads_router
    monkeypatch.setattr(leads_router, "MAX_CSV_BYTES", 50)

    body = _csv("alex@example.com,Alex,,,,,,,,,," + "x" * 100)
    r = await client.post("/leads/import-csv", files={"file": ("big.csv", body, "text/csv")})
    assert r.status_code == 413


async def test_oversized_row_count_is_413(client, monkeypatch):
    from app.routers import leads as leads_router
    monkeypatch.setattr(leads_router, "MAX_CSV_ROWS", 1)

    body = _csv(
        "a@example.com,A,,,,,,,,,,",
        "b@example.com,B,,,,,,,,,,",
    )
    r = await client.post("/leads/import-csv", files={"file": ("many.csv", body, "text/csv")})
    assert r.status_code == 413
