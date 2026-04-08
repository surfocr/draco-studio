"""Tests for provider API endpoints not covered by test_health.py."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_provider_health_returns_structure(client):
    """GET /api/providers/health returns providers map and all_ok flag."""
    r = await client.get("/api/providers/health")
    assert r.status_code == 200
    body = r.json()
    assert "providers" in body
    assert "all_ok" in body
    assert isinstance(body["providers"], dict)
    assert isinstance(body["all_ok"], bool)


@pytest.mark.asyncio
async def test_list_provider_configs_returns_dict(client):
    """GET /api/providers/configs returns a configs dict."""
    r = await client.get("/api/providers/configs")
    assert r.status_code == 200
    body = r.json()
    assert "configs" in body
    assert isinstance(body["configs"], dict)


@pytest.mark.asyncio
async def test_list_providers_by_type_returns_type_and_list(client):
    """GET /api/providers/{type} returns type echo and providers list."""
    r = await client.get("/api/providers/caption")
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "caption"
    assert isinstance(body["providers"], list)


@pytest.mark.asyncio
async def test_list_providers_by_nonexistent_type_returns_empty(client):
    """GET /api/providers/{type} with unknown type returns empty list."""
    r = await client.get("/api/providers/nonexistent_type_xyz")
    assert r.status_code == 200
    body = r.json()
    assert body["type"] == "nonexistent_type_xyz"
    assert body["providers"] == []


@pytest.mark.asyncio
async def test_test_provider_returns_404_for_missing(client):
    """POST /api/providers/{type}/{name}/test returns 404 when provider missing."""
    r = await client.post("/api/providers/caption/no_such_provider/test")
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_single_provider_health_missing_returns_error(client):
    """GET /api/providers/{type}/{name}/health returns error for missing provider."""
    r = await client.get("/api/providers/caption/no_such_provider/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["error"] == "Provider not found"


@pytest.mark.asyncio
async def test_list_caption_models_returns_providers_dict(client):
    """GET /api/providers/caption/models returns providers dict."""
    r = await client.get("/api/providers/caption/models")
    assert r.status_code == 200
    body = r.json()
    assert "providers" in body
    assert isinstance(body["providers"], dict)


@pytest.mark.asyncio
async def test_save_api_key_success(client):
    """POST /api/providers/api-key with valid data returns saved status."""
    r = await client.post(
        "/api/providers/api-key",
        json={
            "provider_type": "caption",
            "provider_name": "test_provider_save",
            "api_key": "sk-test-key-12345",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "saved"
    assert body["provider_name"] == "test_provider_save"


@pytest.mark.asyncio
async def test_get_api_key_status_returns_dict(client):
    """GET /api/providers/api-key-status is shadowed by /{provider_type} wildcard.

    The api-key-status route is registered after the /{provider_type} path
    parameter route, so FastAPI matches the wildcard first.  This test
    documents the current (shadowed) behaviour.
    """
    r = await client.get("/api/providers/api-key-status")
    assert r.status_code == 200
    body = r.json()
    # Route is currently intercepted by list_providers_by_type
    assert body["type"] == "api-key-status"
    assert isinstance(body["providers"], list)
