"""
Shared test fixtures — in-memory SQLite database and FastAPI test client.

Uses shared-cache in-memory SQLite so all connections see the same tables/data.
"""
from __future__ import annotations

import os
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

# Shared-cache in-memory SQLite: every connection sees the same database.
TEST_DATABASE_URL = "sqlite+aiosqlite:///file:testdb?mode=memory&cache=shared&uri=true"

os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)
os.environ.setdefault("DRACO_SECRET_KEY", "test-secret-key-32chars-padding!!")
os.environ.setdefault("ALLOW_REMOTE_ACCESS", "true")


@pytest_asyncio.fixture(scope="session")
async def engine():
    from database import Base
    eng = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        poolclass=StaticPool,
    )
    async with eng.begin() as conn:
        import models  # noqa: F401 — populate metadata
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine):
    """Yield a fresh async session per test, rolled back after."""
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(engine):
    """FastAPI test client wired to the in-memory database."""
    from database import get_db
    from main import app

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
