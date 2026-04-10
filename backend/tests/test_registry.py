"""Tests for providers/registry.py — ProviderRegistry."""
from __future__ import annotations

import pytest
from providers.registry import ProviderRegistry, safe_register_provider
from providers.base import ProviderBase


class DummyProvider(ProviderBase):
    """Minimal provider for testing."""
    def __init__(self, **kwargs):
        self.cfg = kwargs

    async def health_check(self) -> dict:
        return {"ok": True, "provider": "dummy"}

    async def is_available(self) -> bool:
        return True

    async def load(self) -> None:
        pass


class BadProvider(ProviderBase):
    """Provider that raises on instantiation."""
    def __init__(self, **kwargs):
        raise RuntimeError("Cannot init")

    async def health_check(self) -> dict:
        return {"ok": False}

    async def is_available(self) -> bool:
        return False


class UnavailableProvider(ProviderBase):
    """Provider that says it's not available."""
    async def health_check(self) -> dict:
        return {"ok": False, "error": "not available"}

    async def is_available(self) -> bool:
        return False

    async def load(self) -> None:
        pass


@pytest.fixture
def registry():
    return ProviderRegistry()


def test_register_and_get(registry):
    registry.register("test", "dummy", DummyProvider)
    provider = registry.get("test", "dummy")
    assert provider is not None
    assert isinstance(provider, DummyProvider)


def test_get_unregistered_type(registry):
    assert registry.get("nonexistent", "foo") is None


def test_get_unregistered_name(registry):
    registry.register("test", "dummy", DummyProvider)
    assert registry.get("test", "other") is None


def test_lazy_instantiation(registry):
    registry.register("test", "dummy", DummyProvider)
    # No instance yet
    assert "test" not in registry._instances or "dummy" not in registry._instances.get("test", {})
    # First get triggers instantiation
    p = registry.get("test", "dummy")
    assert p is not None
    # Second get returns same instance
    assert registry.get("test", "dummy") is p


def test_get_returns_none_on_failed_init(registry):
    registry.register("test", "bad", BadProvider)
    assert registry.get("test", "bad") is None


def test_get_typed(registry):
    registry.register("test", "dummy", DummyProvider)
    p = registry.get_typed("test", "dummy", DummyProvider)
    assert isinstance(p, DummyProvider)


def test_get_typed_wrong_type(registry):
    registry.register("test", "dummy", DummyProvider)
    # Wrong type returns None
    p = registry.get_typed("test", "dummy", UnavailableProvider)
    assert p is None


def test_get_default(registry):
    registry.register("test", "first", DummyProvider)
    registry.register("test", "second", DummyProvider)
    p = registry.get_default("test")
    assert p is not None


def test_get_default_empty(registry):
    assert registry.get_default("nonexistent") is None


def test_list_available(registry):
    registry.register("test", "a", DummyProvider)
    registry.register("test", "b", DummyProvider)
    assert sorted(registry.list_available("test")) == ["a", "b"]


def test_list_available_empty(registry):
    assert registry.list_available("nonexistent") == []


def test_list_all_types(registry):
    registry.register("caption", "a", DummyProvider)
    registry.register("face", "b", DummyProvider)
    types = registry.list_all_types()
    assert "caption" in types
    assert "face" in types


def test_set_config_invalidates_instance(registry):
    registry.register("test", "dummy", DummyProvider, config={"x": 1})
    p1 = registry.get("test", "dummy")
    assert p1.cfg.get("x") == 1
    # Changing config invalidates instance
    registry.set_config("test", "dummy", {"x": 2})
    p2 = registry.get("test", "dummy")
    assert p2.cfg.get("x") == 2
    assert p1 is not p2


def test_re_register_invalidates_instance(registry):
    registry.register("test", "dummy", DummyProvider)
    p1 = registry.get("test", "dummy")
    registry.register("test", "dummy", DummyProvider)
    p2 = registry.get("test", "dummy")
    assert p1 is not p2


@pytest.mark.asyncio
async def test_health_check_all(registry):
    registry.register("test", "dummy", DummyProvider)
    results = await registry.health_check_all()
    assert "test" in results
    assert results["test"]["dummy"]["ok"] is True


@pytest.mark.asyncio
async def test_health_check_all_handles_failed_instantiation(registry):
    registry.register("test", "bad", BadProvider)
    results = await registry.health_check_all()
    assert results["test"]["bad"]["ok"] is False


@pytest.mark.asyncio
async def test_check_available_true(registry):
    registry.register("test", "dummy", DummyProvider)
    result = await registry.check_available("test", "dummy")
    assert result is True


@pytest.mark.asyncio
async def test_check_available_false(registry):
    registry.register("test", "unavail", UnavailableProvider)
    result = await registry.check_available("test", "unavail")
    assert result is False


@pytest.mark.asyncio
async def test_check_available_not_registered(registry):
    result = await registry.check_available("test", "nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_check_available_caching(registry):
    registry.register("test", "dummy", DummyProvider)
    await registry.check_available("test", "dummy")
    # Should be cached
    assert ("test", "dummy") in registry._availability_cache


@pytest.mark.asyncio
async def test_load_all(registry):
    registry.register("test", "dummy", DummyProvider)
    await registry.load_all()  # Should not raise


def test_safe_register_provider_success(registry):
    result = safe_register_provider(
        registry, "storage", "local",
        "providers.storage.local", "LocalStorageProvider",
    )
    assert result is True
    assert "local" in registry.list_available("storage")


def test_safe_register_provider_import_failure(registry):
    result = safe_register_provider(
        registry, "test", "nonexistent",
        "nonexistent.module", "NonexistentClass",
    )
    assert result is False


def test_repr(registry):
    registry.register("test", "dummy", DummyProvider)
    r = repr(registry)
    assert "test" in r
    assert "dummy" in r
