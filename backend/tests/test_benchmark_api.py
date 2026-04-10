"""Tests for benchmark API endpoints."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_list_benchmark_providers(client):
    """GET /api/benchmark/providers/{type} returns provider list."""
    r = await client.get("/api/benchmark/providers/caption")
    assert r.status_code == 200
    body = r.json()
    assert "providers" in body
    assert body["provider_type"] == "caption"
    assert isinstance(body["providers"], list)


@pytest.mark.asyncio
async def test_list_benchmark_providers_unknown_type(client):
    """Unknown provider type returns empty list, not error."""
    r = await client.get("/api/benchmark/providers/nonexistent_type")
    assert r.status_code == 200
    assert r.json()["providers"] == []


@pytest.mark.asyncio
async def test_run_benchmark_rejects_single_provider(client):
    """Must provide at least 2 providers."""
    r = await client.post("/api/benchmark/run", json={
        "provider_type": "caption",
        "provider_names": ["ollama"],
        "asset_ids": ["a1"],
    })
    assert r.status_code == 400
    assert "at least 2" in r.json()["detail"]


@pytest.mark.asyncio
async def test_run_benchmark_rejects_empty_assets(client):
    """Must provide at least one asset ID."""
    r = await client.post("/api/benchmark/run", json={
        "provider_type": "caption",
        "provider_names": ["ollama", "gemini"],
        "asset_ids": [],
    })
    assert r.status_code == 400
    assert "No asset" in r.json()["detail"]


@pytest.mark.asyncio
async def test_run_benchmark_returns_job_id(client):
    """Valid request returns job_id."""
    r = await client.post("/api/benchmark/run", json={
        "provider_type": "caption",
        "provider_names": ["ollama", "gemini"],
        "asset_ids": ["asset-1", "asset-2"],
    })
    assert r.status_code == 200
    body = r.json()
    assert "job_id" in body
    assert body["provider_count"] == 2
    assert body["asset_count"] == 2
