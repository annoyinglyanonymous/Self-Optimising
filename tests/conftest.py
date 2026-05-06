"""
Test fixtures.

Pure tests (no DB) run anywhere. Tests that take the `db_session` or `client`
fixtures require a separate Postgres test database — set TEST_DATABASE_URL in
the environment before running, or those tests will skip:

    set TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/test_db
    .venv/Scripts/python.exe -m pytest

NEVER point TEST_DATABASE_URL at your production database — the fixtures drop
and recreate every table at the start of each test session and TRUNCATE all
tables after each test.
"""
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app import models  # noqa: F401  ensure models register on Base.metadata


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
TEST_JWT_SECRET = "test-jwt-secret-do-not-use-in-prod"


@pytest_asyncio.fixture(scope="session")
async def db_engine():
    if not TEST_DATABASE_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    engine = create_async_engine(TEST_DATABASE_URL, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Session for test setup and assertions. Routes called via the `client`
    fixture get their own short-lived sessions (see `_override_get_db` below)
    that commit independently — this session reads committed state."""
    Session = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with Session() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture(autouse=True)
async def _truncate_after(request):
    """Wipe every table after each test that touches the DB. Routes commit
    through their own sessions, so transactional rollback isn't enough.

    Don't depend on `db_engine` directly — that would skip every pure test
    when TEST_DATABASE_URL isn't set. We only resolve it when actually needed.
    """
    yield
    if "db_session" not in request.fixturenames and "client" not in request.fixturenames:
        return
    db_engine = request.getfixturevalue("db_engine")
    table_names = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    async with db_engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture
async def client(db_engine, monkeypatch):
    """httpx.AsyncClient bound to the FastAPI app via ASGITransport.

    AsyncClient runs the ASGI app on the same event loop as the test, so the
    test fixtures and the route handlers share the same asyncpg connection
    pool. The sync `fastapi.testclient.TestClient` runs the app in a worker
    thread / separate loop, which breaks asyncpg.

    `get_db` is overridden to use the test engine. We also point
    `app.database.engine` / `AsyncSessionLocal` at the test DB so the startup
    hook (`Base.metadata.create_all`, secret validation, scheduler.start)
    doesn't touch the real database. JWT_SECRET is set so `/auth/login`
    works without extra fixtures.
    """
    from app import database, main
    from app.config import settings as app_settings

    test_session_maker = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    monkeypatch.setattr(database, "engine", db_engine)
    monkeypatch.setattr(database, "AsyncSessionLocal", test_session_maker)
    # main.py captured these by reference at import time.
    monkeypatch.setattr(main, "engine", db_engine)
    monkeypatch.setattr(main, "AsyncSessionLocal", test_session_maker)
    monkeypatch.setattr(app_settings, "JWT_SECRET", TEST_JWT_SECRET)

    async def _override_get_db():
        async with test_session_maker() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    main.app.dependency_overrides[database.get_db] = _override_get_db
    try:
        async with main.app.router.lifespan_context(main.app):
            transport = ASGITransport(app=main.app)
            async with AsyncClient(transport=transport, base_url="http://test") as c:
                yield c
    finally:
        main.app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def auth_headers(db_session, monkeypatch):
    """Create a User and return Authorization headers for a valid JWT.
    Sets a test JWT secret for the duration of the test."""
    from app.config import settings as app_settings
    from app.models import User
    from app.services.auth import create_access_token, hash_password

    monkeypatch.setattr(app_settings, "JWT_SECRET", TEST_JWT_SECRET)

    user = User(email="tester@example.com", password_hash=hash_password("pw12345678"))
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = create_access_token(str(user.id), user.email)
    return {"Authorization": f"Bearer {token}"}
