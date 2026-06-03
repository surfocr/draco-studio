from __future__ import annotations

import sys
import types

import pytest

from models.project import Project
from models.project_runtime_config import ProjectRuntimeConfig
from providers.base import ProviderBase
from providers.registry import get_registry, safe_register_provider
from services.runtime_config import DEFAULT_TASK_PROVIDER_OPTIONS


class CountingProvider(ProviderBase):
    provider_id = "counting"
    calls = 0

    async def is_available(self) -> bool:
        type(self).calls += 1
        return True

    async def health_check(self) -> dict:
        return {"ok": True, "latency_ms": 0.0, "details": {}}


async def _create_project(db, name: str = "runtime-config") -> Project:
    project = Project(name=name, description="")
    db.add(project)
    await db.flush()
    return project


@pytest.mark.asyncio
async def test_runtime_get_does_not_persist_default_config(client, db):
    project = await _create_project(db)
    await db.commit()

    response = await client.get(f"/api/projects/{project.id}/runtime")
    assert response.status_code == 200, response.text

    row = await db.get(ProjectRuntimeConfig, project.id)
    assert row is None


@pytest.mark.asyncio
async def test_runtime_patch_creates_persisted_config(client, db):
    project = await _create_project(db, "runtime-patch")
    await db.commit()

    response = await client.patch(
        f"/api/projects/{project.id}/runtime",
        json={
            "runtime_mode": "hybrid",
            "task_provider_overrides": {"caption": "ollama"},
        },
    )
    assert response.status_code == 200, response.text

    row = await db.get(ProjectRuntimeConfig, project.id)
    assert row is not None
    assert row.runtime_mode == "hybrid"
    assert row.task_provider_overrides["caption"] == "ollama"


@pytest.mark.asyncio
async def test_provider_registry_availability_cache():
    registry = get_registry()
    registry._classes.clear()
    registry._instances.clear()
    registry._configs.clear()
    registry._availability_cache.clear()
    CountingProvider.calls = 0
    registry.register("caption", "counting", CountingProvider)

    first = await registry.check_available("caption", "counting")
    second = await registry.check_available("caption", "counting")

    assert first is True
    assert second is True
    assert CountingProvider.calls == 1


def test_safe_register_provider_uses_consistent_import_path():
    module = types.ModuleType("test_registry_provider_module")

    class DummyProvider(ProviderBase):
        provider_id = "dummy"

        async def is_available(self) -> bool:
            return True

        async def health_check(self) -> dict:
            return {"ok": True}

    module.DummyProvider = DummyProvider
    sys.modules[module.__name__] = module
    registry = get_registry()
    registry._classes.clear()
    registry._instances.clear()
    registry._configs.clear()

    try:
        registered = safe_register_provider(
            registry,
            "caption",
            "dummy",
            module.__name__,
            "DummyProvider",
        )
    finally:
        sys.modules.pop(module.__name__, None)

    assert registered is True
    assert "dummy" in registry.list_available("caption")


def test_safe_register_provider_swallows_runtime_import_failures(monkeypatch):
    registry = get_registry()
    registry._classes.clear()
    registry._instances.clear()
    registry._configs.clear()

    def boom(_module_path: str):
        raise RuntimeError("native dependency missing")

    monkeypatch.setattr("providers.registry.import_module", boom)

    registered = safe_register_provider(
        registry,
        "caption",
        "broken",
        "providers.caption.broken",
        "BrokenProvider",
    )

    assert registered is False
    assert registry.list_available("caption") == []


def test_caption_runtime_defaults_include_target_model_settings():
    defaults = DEFAULT_TASK_PROVIDER_OPTIONS["caption"]
    assert defaults["target_model"] == "flux_1"
    assert defaults["character_mode"] is False
