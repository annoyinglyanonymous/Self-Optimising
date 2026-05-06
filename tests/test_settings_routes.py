"""Tests for /api/settings/* routes. Skip unless TEST_DATABASE_URL is set."""
from sqlalchemy import select

from app.models import Setting
from app.services import app_settings, encryption


async def test_sender_status_default_is_stub_with_others_unconfigured(client):
    r = await client.get("/api/settings/sender-status")
    assert r.status_code == 200
    body = r.json()
    assert body["active"] == "stub"
    assert body["backends"]["stub"]["ready"] is True
    assert body["backends"]["gmail"]["ready"] is False
    assert "GMAIL_USERNAME" in body["backends"]["gmail"]["missing"]


async def test_credentials_masks_secrets(client, db_session, monkeypatch):
    # Need a real ENCRYPTION_KEY to write/read encrypted rows.
    from cryptography.fernet import Fernet
    test_key = Fernet.generate_key().decode()
    from app.config import settings as app_cfg
    monkeypatch.setattr(app_cfg, "ENCRYPTION_KEY", test_key)
    # Force the lazy Fernet singleton to reload with the test key.
    monkeypatch.setattr(encryption, "_fernet", None)

    await app_settings.set(db_session, "INSTANTLY_API_KEY", "super-secret-token")
    await app_settings.set(db_session, "INSTANTLY_DEFAULT_CAMPAIGN_ID", "camp_123")
    await db_session.commit()

    r = await client.get("/api/settings/credentials")
    assert r.status_code == 200
    body = r.json()
    inst = body["instantly"]
    assert inst["INSTANTLY_API_KEY"]["value"] == "***"
    assert inst["INSTANTLY_API_KEY"]["is_set"] is True
    # Non-secret values come back as-is.
    assert inst["INSTANTLY_DEFAULT_CAMPAIGN_ID"]["value"] == "camp_123"


async def test_put_credentials_round_trip(client, db_session, monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setattr(__import__("app.config", fromlist=["settings"]).settings, "ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(encryption, "_fernet", None)

    r = await client.put("/api/settings/credentials", json={"values": {
        "GMAIL_USERNAME": "bot@example.com",
        "GMAIL_APP_PASSWORD": "abcd-efgh-ijkl-mnop",
    }})
    assert r.status_code == 200
    assert set(r.json()["updated"]) == {"GMAIL_USERNAME", "GMAIL_APP_PASSWORD"}

    # Round-trip: reading back as-stored should match.
    assert await app_settings.get(db_session, "GMAIL_USERNAME") == "bot@example.com"
    assert await app_settings.get(db_session, "GMAIL_APP_PASSWORD") == "abcd-efgh-ijkl-mnop"


async def test_put_credentials_mask_value_is_no_op_for_secrets(client, db_session, monkeypatch):
    from cryptography.fernet import Fernet
    from app.config import settings as app_cfg
    monkeypatch.setattr(app_cfg, "ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(encryption, "_fernet", None)

    await app_settings.set(db_session, "GMAIL_APP_PASSWORD", "real-password")
    await db_session.commit()

    # The dashboard re-submits the masked form; "***" must NOT clobber the real value.
    r = await client.put("/api/settings/credentials", json={"values": {"GMAIL_APP_PASSWORD": "***"}})
    assert r.status_code == 200
    assert r.json()["updated"] == []  # masked secret was skipped

    assert await app_settings.get(db_session, "GMAIL_APP_PASSWORD") == "real-password"


async def test_put_credentials_unknown_key_is_400(client):
    r = await client.put("/api/settings/credentials", json={"values": {"NOT_A_KEY": "x"}})
    assert r.status_code == 400
    assert "unknown key" in r.json()["detail"]


async def test_put_credentials_empty_string_clears_db_row(client, db_session):
    db_session.add(Setting(key="GMAIL_USERNAME", value="old@example.com", is_secret=False))
    await db_session.commit()

    r = await client.put("/api/settings/credentials", json={"values": {"GMAIL_USERNAME": ""}})
    assert r.status_code == 200

    row = (await db_session.execute(
        select(Setting).where(Setting.key == "GMAIL_USERNAME")
    )).scalar_one()
    await db_session.refresh(row)
    assert row.value == ""


async def test_set_sender_backend_route(client, db_session):
    r = await client.post("/api/settings/sender-backend", json={"backend": "gmail"})
    assert r.status_code == 200
    assert r.json()["backend"] == "gmail"
    assert await app_settings.get(db_session, "SENDER_BACKEND") == "gmail"


async def test_set_sender_backend_invalid_choice_is_400(client):
    r = await client.post("/api/settings/sender-backend", json={"backend": "carrier-pigeon"})
    assert r.status_code == 400


async def test_test_connection_stub_always_ok(client):
    r = await client.post("/api/settings/test-connection", json={"backend": "stub"})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "error": None}


async def test_require_approval_toggle_persists(client, db_session):
    r = await client.put("/api/settings/credentials", json={"values": {"REQUIRE_APPROVAL": "true"}})
    assert r.status_code == 200
    assert await app_settings.get(db_session, "REQUIRE_APPROVAL") == "true"

    # Reads come back through the credentials endpoint's "behavior" bucket.
    r2 = await client.get("/api/settings/credentials")
    assert r2.json()["behavior"]["REQUIRE_APPROVAL"] == "true"
