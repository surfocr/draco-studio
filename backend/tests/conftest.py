"""
Shared test fixtures — in-memory SQLite database and FastAPI test client.
"""
from __future__ import annotations

import os
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Use a shared in-memory SQLite database for tests (shared cache enables
# multiple connections to see the same in-memory DB).
TEST_DATABASE_URL = (
    "sqlite+aiosqlite:///file:testdb?mode=memory&cache=shared&uri=true"
)

os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL)
os.environ.setdefault("DRACO_SECRET_KEY", "test-secret-key-32chars-padding!!")
os.environ.setdefault("ALLOW_REMOTE_ACCESS", "true")


@pytest_asyncio.fixture(scope="session")
async def engine():
    from database import Base
    from providers.registry import get_registry, register_default_providers

    eng = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with eng.begin() as conn:
        import models  # noqa: F401 — populate metadata
        await conn.run_sync(Base.metadata.create_all)

    register_default_providers(get_registry())

    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def db(engine):
    """Yield a per-test async session isolated by a nested savepoint.

    SQLite's ``RELEASE SAVEPOINT`` commits only when it releases the
    *outermost* savepoint.  By placing an outer savepoint before handing the
    session to the test, any inner ``session.commit()`` calls (which issue
    ``SAVEPOINT`` + ``RELEASE``) stay within that outer savepoint and are
    fully undone by the final ``ROLLBACK TO SAVEPOINT`` + ``ROLLBACK``.
    """
    async with engine.connect() as connection:
        await connection.begin()
        outer_sp = await connection.begin_nested()   # outer SAVEPOINT — never released
        session = AsyncSession(
            bind=connection,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        try:
            yield session
        finally:
            await session.close()
            await outer_sp.rollback()   # ROLLBACK TO SAVEPOINT — undoes all inner work
            await connection.rollback() # ROLLBACK — closes the outer transaction


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
