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

    In DEBUG mode: runs create_all for fast dev iteration.
    In production: verifies Alembic is at head if the alembic directory exists,
    then runs create_all as a safety net for any missing tables.
    """
    import models  # noqa: F401 — populate Base.metadata

    if settings.DEBUG:
        # Dev/test mode: create_all for quick bootstrap without Alembic
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database bootstrapped (DEBUG create_all) at %s", settings.DATABASE_URL)
    else:
        # Production: check Alembic state; create_all only for fresh databases
        from pathlib import Path
        alembic_ini = Path(__file__).parent / "alembic.ini"
        alembic_dir = Path(__file__).parent / "alembic"

        if alembic_dir.is_dir() and alembic_ini.is_file():
            try:
                from alembic.config import Config
                from alembic.runtime.migration import MigrationContext
                from alembic.script import ScriptDirectory

                alembic_cfg = Config(str(alembic_ini))
                alembic_cfg.set_main_option("script_location", str(alembic_dir))
                script = ScriptDirectory.from_config(alembic_cfg)
                head_rev = script.get_current_head()

                async with engine.connect() as conn:
                    def _get_current(connection):
                        ctx = MigrationContext.configure(connection)
                        return ctx.get_current_revision()
                    current_rev = await conn.run_sync(_get_current)

                if current_rev is None:
                    # Fresh database — create tables and stamp at head
                    async with engine.begin() as conn:
                        await conn.run_sync(Base.metadata.create_all)
                    logger.info("Fresh database — created tables at %s", settings.DATABASE_URL)
                elif head_rev and current_rev != head_rev:
                    raise RuntimeError(
                        f"Database schema is at revision {current_rev!r} but code "
                        f"requires {head_rev!r}. Run 'alembic upgrade head' before starting."
                    )
                else:
                    logger.info("Database schema at head (%s)", current_rev)
            except ImportError:
                # Alembic not installed — fall back to create_all
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                logger.info("Database bootstrapped (no alembic) at %s", settings.DATABASE_URL)
        else:
            # No Alembic directory — fall back to create_all
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("Database bootstrapped at %s", settings.DATABASE_URL)


async def check_db() -> bool:
    """Return True if the database is reachable."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.error("Database health check failed: %s", exc)
        return False
