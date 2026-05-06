"""Auth router integration tests. Skip unless TEST_DATABASE_URL is set."""
from sqlalchemy import select

from app.models import User
from app.services.auth import hash_password


async def _seed_user(db_session, email: str, password: str, is_active: bool = True) -> User:
    user = User(email=email, password_hash=hash_password(password), is_active=is_active)
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def test_login_success_returns_token_and_user(client, db_session):
    await _seed_user(db_session, "alice@example.com", "secret-password-1")

    r = await client.post("/auth/login", json={"email": "alice@example.com", "password": "secret-password-1"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["user"]["email"] == "alice@example.com"
    # last_login_at should be set after a successful login.
    refreshed = (await db_session.execute(
        select(User).where(User.email == "alice@example.com")
    )).scalar_one()
    await db_session.refresh(refreshed)
    assert refreshed.last_login_at is not None


async def test_login_wrong_password_is_401_with_generic_message(client, db_session):
    await _seed_user(db_session, "bob@example.com", "correct-password")

    r = await client.post("/auth/login", json={"email": "bob@example.com", "password": "wrong"})

    assert r.status_code == 401
    # Same message as "no such user" — don't leak which emails exist.
    assert r.json()["detail"] == "Invalid email or password"


async def test_login_unknown_email_uses_same_401_message(client):
    r = await client.post("/auth/login", json={"email": "nobody@example.com", "password": "x"})
    assert r.status_code == 401
    assert r.json()["detail"] == "Invalid email or password"


async def test_login_inactive_user_returns_403(client, db_session):
    await _seed_user(db_session, "carol@example.com", "pw", is_active=False)

    r = await client.post("/auth/login", json={"email": "carol@example.com", "password": "pw"})

    assert r.status_code == 403
    assert "inactive" in r.json()["detail"].lower()


async def test_me_with_valid_token_returns_user_info(client, auth_headers):
    r = await client.get("/auth/me", headers=auth_headers)

    assert r.status_code == 200
    body = r.json()
    assert body["email"] == "tester@example.com"
    assert body["is_active"] is True


async def test_me_without_token_returns_401(client):
    r = await client.get("/auth/me")
    assert r.status_code == 401


async def test_me_with_garbage_token_returns_401(client):
    r = await client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-jwt"})
    assert r.status_code == 401
