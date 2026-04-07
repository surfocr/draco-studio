"""
Shared test fixtures — in-memory SQLite database and FastAPI test client.
"""
from __future__ import annotations

import os
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("DRACO_SECRET_KEY", "test-secret-key-32chars-padding!!")


@pytest_asyncio.fixture
async def engine(tmp_path):
    """Create a fresh file-based SQLite database per test.

    A file-based database lets every connection (including those opened by
    background tasks or the job queue) see the same tables that were created
    during fixture setup, without sharing a single connection object.
    """
    from database import Base
    db_path = tmp_path / "test.db"
    url = f"sqlite+aiosqlite:///{db_path}"
    eng = create_async_engine(url, echo=False)
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


@pytest.fixture
def storage_env(tmp_path, monkeypatch):
    """Patch settings to point at a temporary directory and ensure default
    storage/quality providers are registered for any test that calls services
    relying on the provider registry (e.g. ingest, caption export)."""
    from config import settings
    from providers.registry import get_registry, register_default_providers

    monkeypatch.setattr(settings, "STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path / "data"))
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    registry = get_registry()
    registry._instances.clear()
    register_default_providers(registry)
    yield tmp_path
    registry._instances.clear()


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
