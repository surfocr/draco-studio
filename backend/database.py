"""
SQLAlchemy 2.0 async database setup.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from config import settings

logger = logging.getLogger(__name__)

# ── Engine ────────────────────────────────────────────────────────────────────

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    # SQLite-specific: WAL mode + busy timeout
    connect_args={
        "check_same_thread": False,
        "timeout": 30,
    },
)


@event.listens_for(engine.sync_engine, "connect")
def _set_sqlite_pragmas(dbapi_conn: Any, _: Any) -> None:
    """Enable WAL mode and foreign keys on every new connection."""
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute("PRAGMA cache_size=-64000")   # 64 MB page cache
    cursor.execute("PRAGMA temp_store=MEMORY")
    cursor.close()


# ── Session factory ───────────────────────────────────────────────────────────

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False,
)


# ── Declarative base ──────────────────────────────────────────────────────────

class Base(AsyncAttrs, DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


# ── FastAPI dependency ────────────────────────────────────────────────────────

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Startup helper ────────────────────────────────────────────────────────────

async def init_db() -> None:
    """Bootstrap the database.

    In DEBUG mode (local dev / tests): runs create_all so the schema is
    available without Alembic.  In production (DEBUG=False): only imports
    models so they register with metadata, then verifies the DB is reachable.
    Production schema management is handled exclusively by Alembic migrations.
    """
    import models  # noqa: F401 — populate Base.metadata

    if settings.DEBUG:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database bootstrapped (create_all) at %s", settings.DATABASE_URL)
    else:
        # Verify connectivity; rely on Alembic for schema
        ok = await check_db()
        if not ok:
            raise RuntimeError(
                f"Database at {settings.DATABASE_URL!r} is not reachable on startup"
            )
        logger.info("Database ready at %s", settings.DATABASE_URL)


async def check_db() -> bool:
    """Return True if the database is reachable."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error("Database health check failed: %s", exc)
        return False
