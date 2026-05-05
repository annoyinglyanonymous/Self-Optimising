"""
Test fixtures.

Pure tests (no DB) run anywhere. Tests that take the `db_session` fixture
require a separate Postgres test database — set TEST_DATABASE_URL in the
environment before running, or those tests will skip:

    set TEST_DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/test_db
    .venv/Scripts/python.exe -m pytest

NEVER point TEST_DATABASE_URL at your production database — the fixture
drops and recreates every table at the start of each test session.
"""
import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.database import Base
from app import models  # noqa: F401  ensure models register on Base.metadata


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


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
    """A fresh session per test. Tests should commit explicitly if they want
    state to persist across queries within the test."""
    Session = async_sessionmaker(
        db_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with Session() as session:
        yield session
        await session.rollback()
