"""Provider config persistence helpers."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.provider_config import ProviderConfig
from providers.registry import get_registry


def decrypt_api_key(encrypted_value: str | None, fernet: Any | None) -> str | None:
    if not encrypted_value or fernet is None:
        return None
    return fernet.decrypt(encrypted_value.encode()).decode()


def build_live_provider_config(
    row: ProviderConfig,
    *,
    fernet: Any | None = None,
) -> dict[str, Any]:
    config = dict(row.config or {})
    api_key = decrypt_api_key(row.api_key_encrypted, fernet)
    if api_key:
        config["api_key"] = api_key
    return config


def apply_provider_config_row(
    row: ProviderConfig,
    *,
    fernet: Any | None = None,
) -> dict[str, Any]:
    config = build_live_provider_config(row, fernet=fernet)
    registry = get_registry()
    registry.set_config(row.provider_type, row.provider_name, config)
    return config


async def apply_all_provider_configs(
    db: AsyncSession,
    *,
    fernet: Any | None = None,
) -> list[dict[str, Any]]:
    result = await db.execute(select(ProviderConfig))
    applied: list[dict[str, Any]] = []
    for row in result.scalars().all():
        config = apply_provider_config_row(row, fernet=fernet)
        applied.append(
            {
                "provider_type": row.provider_type,
                "provider_name": row.provider_name,
                "config_keys": sorted(config.keys()),
            }
        )
    return applied
