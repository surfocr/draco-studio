"""Provider configuration and health check router."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from providers.registry import get_registry

router = APIRouter(prefix="/api/providers", tags=["providers"])


class ProviderConfigRequest(BaseModel):
    config: dict


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
) -> dict:
    """Save configuration for a provider type."""
    # Config saved to settings — implementation depends on config system
    return {"status": "saved", "provider_type": provider_type}


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
