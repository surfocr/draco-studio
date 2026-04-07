"""
Shared test fixtures — SQLite database and FastAPI test client.

Each test gets its own fresh SQLite temp-file database so that:
  - tables created by the engine fixture are visible on all connections
  - data committed by one test never leaks into another
"""
from __future__ import annotations

import os
import tempfile
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("DRACO_SECRET_KEY", "test-secret-key-32chars-padding!!")


@pytest_asyncio.fixture
async def engine():
    """Fresh SQLite file database with full schema for each test."""
    with tempfile.NamedTemporaryFile(suffix=".test.db", delete=False) as f:
        db_path = f.name
    os.unlink(db_path)  # Remove so SQLite creates a clean database

    url = f"sqlite+aiosqlite:///{db_path}"
    os.environ["DATABASE_URL"] = url  # update env so async database module sees it

    from database import Base
    eng = create_async_engine(url, echo=False)
    async with eng.begin() as conn:
        import models  # noqa: F401 — populate metadata
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()
    try:
        os.unlink(db_path)
    except OSError:
        pass


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
    from database import get_db, AsyncSessionLocal
    from sqlalchemy.ext.asyncio import AsyncSession
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
