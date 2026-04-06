"""Provider configuration and health check router."""
from __future__ import annotations

import base64
import os
from typing import Annotated

from cryptography.fernet import Fernet
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.provider_config import ProviderConfig
from providers.registry import get_registry

router = APIRouter(prefix="/api/providers", tags=["providers"])


def _get_fernet() -> Fernet:
    """Return a Fernet instance keyed from DRACO_SECRET_KEY env var.
    Raises RuntimeError if the variable is not set — never falls back to a derived key."""
    raw = os.environ.get("DRACO_SECRET_KEY")
    if not raw:
        raise RuntimeError(
            "DRACO_SECRET_KEY environment variable is not set. "
            "Set it to a non-empty secret string to enable provider API key storage."
        )
    key = base64.urlsafe_b64encode(raw.encode()[:32].ljust(32, b"\x00"))
    return Fernet(key)


class ProviderConfigRequest(BaseModel):
    config: dict


class ApiKeyRequest(BaseModel):
    provider_type: str
    provider_name: str
    api_key: str


@router.get("/health")
async def provider_health() -> dict:
    """Health check all registered providers."""
    registry = get_registry()
    results = await registry.health_check_all()
    return {
        "providers": results,
        "all_ok": all(
            v.get("ok", False)
            for ptype in results.values()
            for v in (ptype.values() if isinstance(ptype, dict) else [ptype])
        ),
    }


@router.get("")
async def list_providers() -> dict:
    """List all registered providers by type."""
    registry = get_registry()
    all_types = registry.list_all_types()
    return {
        "providers": {
            ptype: registry.list_available(ptype)
            for ptype in all_types
        }
    }


@router.get("/{provider_type}")
async def list_providers_by_type(provider_type: str) -> dict:
    """List providers for a specific type."""
    registry = get_registry()
    available = registry.list_available(provider_type)
    return {"type": provider_type, "providers": available}


@router.post("/{provider_type}/config")
async def save_provider_config(
    provider_type: str,
    body: ProviderConfigRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Save non-secret configuration for a provider type."""
    provider_name = body.config.get("provider_name", "default")
    result = await db.execute(
        select(ProviderConfig).where(
            ProviderConfig.provider_type == provider_type,
            ProviderConfig.provider_name == provider_name,
        )
    )
    row = result.scalar_one_or_none()
    if row:
        row.config = {k: v for k, v in body.config.items() if k != "provider_name"}
    else:
        row = ProviderConfig(
            provider_type=provider_type,
            provider_name=provider_name,
            config={k: v for k, v in body.config.items() if k != "provider_name"},
        )
        db.add(row)
    await db.commit()
    return {"status": "saved", "provider_type": provider_type, "provider_name": provider_name}


@router.post("/api-key")
async def save_api_key(
    body: ApiKeyRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Store an API key encrypted in the database. Never returns the key."""
    fernet = _get_fernet()
    encrypted = fernet.encrypt(body.api_key.encode()).decode()

    result = await db.execute(
        select(ProviderConfig).where(
            ProviderConfig.provider_type == body.provider_type,
            ProviderConfig.provider_name == body.provider_name,
        )
    )
    row = result.scalar_one_or_none()
    if row:
        row.api_key_encrypted = encrypted
    else:
        row = ProviderConfig(
            provider_type=body.provider_type,
            provider_name=body.provider_name,
            api_key_encrypted=encrypted,
        )
        db.add(row)
    await db.commit()
    return {"status": "saved", "provider_name": body.provider_name}


@router.get("/api-key-status")
async def get_api_key_status(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Return which providers have a key stored (boolean map — never the keys themselves)."""
    result = await db.execute(
        select(ProviderConfig.provider_name, ProviderConfig.api_key_encrypted)
    )
    status = {
        row.provider_name: row.api_key_encrypted is not None
        for row in result
    }
    return {"status": status}


@router.post("/{provider_type}/{provider_name}/test")
async def test_provider(provider_type: str, provider_name: str) -> dict:
    """Run a health check on a specific provider."""
    registry = get_registry()
    provider = registry.get(provider_type, provider_name)
    if not provider:
        raise HTTPException(
            status_code=404,
            detail=f"Provider {provider_type}/{provider_name} not found",
        )
    result = await provider.health_check()
    return result


@router.get("/{provider_type}/{provider_name}/health")
async def single_provider_health(provider_type: str, provider_name: str) -> dict:
    """Health check a single provider."""
    registry = get_registry()
    provider = registry.get(provider_type, provider_name)
    if not provider:
        return {"ok": False, "error": "Provider not found"}
    return await provider.health_check()


@router.get("/caption/models")
async def list_caption_models() -> dict:
    """List available models for each caption provider."""
    registry = get_registry()
    result: dict[str, list] = {}
    for name in registry.list_available("caption"):
        provider = registry.get("caption", name)
        if not provider:
            continue
        models: list = []
        if hasattr(provider, "list_models"):
            try:
                models = await provider.list_models()
            except Exception:
                pass
        result[name] = models
    return {"providers": result}
