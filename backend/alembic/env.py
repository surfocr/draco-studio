"""Alembic env.py — async SQLite configuration."""
from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# Ensure backend/ is on sys.path so 'database', 'models', etc. are importable
_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# Load app config
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import all models so metadata is populated
from database import Base  # noqa: E402
from models.project import Project  # noqa: E402, F401
from models.asset import Asset  # noqa: E402, F401
from models.caption import CaptionVersion  # noqa: E402, F401
from models.face import FaceCluster, IdentityCluster  # noqa: E402, F401
from models.ranking import RankingSession, RankingComparison  # noqa: E402, F401
from models.augmentation import AugmentationJob, AugmentationResult  # noqa: E402, F401
from models.export import ExportJob  # noqa: E402, F401
from models.provider_config import ProviderConfig  # noqa: E402, F401
from models.preferences import UserPreferences  # noqa: E402, F401

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    url = config.get_main_option("sqlalchemy.url")
    connectable = create_async_engine(url, poolclass=pool.NullPool)
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
