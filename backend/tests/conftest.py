"""
Shared test fixtures — file-based temp SQLite database and FastAPI test client.
"""
from __future__ import annotations

import os
import tempfile
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Create a temp file database that persists across the test session
_db_fd, _db_path = tempfile.mkstemp(suffix=".db")
os.close(_db_fd)

TEST_DATABASE_URL = f"sqlite+aiosqlite:///{_db_path}"

os.environ["DATABASE_URL"] = TEST_DATABASE_URL
os.environ.setdefault("DRACO_SECRET_KEY", "test-secret-key-32chars-padding!!")
os.environ["DEBUG"] = "1"


@pytest_asyncio.fixture(scope="session")
async def engine():
    eng = create_async_engine(
        TEST_DATABASE_URL,
        echo=False,
        connect_args={"check_same_thread": False},
    )

    # Patch the module-level database objects so the entire app uses this engine
    import database
    database.engine = eng
    database.AsyncSessionLocal = async_sessionmaker(
        bind=eng, class_=AsyncSession, expire_on_commit=False, autoflush=False, autocommit=False,
    )

    # Create all tables
    from database import Base
    async with eng.begin() as conn:
        import models  # noqa: F401 — populate metadata
        await conn.run_sync(Base.metadata.create_all)

    yield eng
    await eng.dispose()

    # Clean up temp file
    try:
        os.unlink(_db_path)
    except OSError:
        pass


@pytest_asyncio.fixture
async def db(engine):
    """Yield a fresh async session per test, rolled back after."""
    import database
    async with database.AsyncSessionLocal() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(engine):
    """FastAPI test client wired to the shared database."""
    from database import get_db
    from main import app

    app.dependency_overrides[get_db] = _override_get_db

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


async def _override_get_db():
    import database
    async with database.AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
