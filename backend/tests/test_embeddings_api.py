"""Tests for embeddings API endpoints."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from models.asset import Asset
from models.project import Project


async def _project(db) -> Project:
    p = Project(name="embed-test", description="")
    db.add(p)
    await db.flush()
    return p


async def _asset(db, project_id) -> Asset:
    a = Asset(
        project_id=project_id,
        filename="embed.png",
        filepath="/tmp/fake/embed.png",
        mime_type="image/png",
        width=512, height=512,
    )
    db.add(a)
    await db.flush()
    return a


@pytest.mark.asyncio
async def test_index_project_returns_queued(client, db):
    """POST /api/embeddings/index returns queued status."""
    project = await _project(db)
    await db.commit()
    r = await client.post("/api/embeddings/index", json={
        "project_id": project.id,
        "force": False,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "queued"
    assert body["project_id"] == project.id
    assert body["force"] is False


@pytest.mark.asyncio
async def test_index_project_with_force(client, db):
    project = await _project(db)
    await db.commit()
    r = await client.post("/api/embeddings/index", json={
        "project_id": project.id,
        "force": True,
    })
    assert r.status_code == 200
    assert r.json()["force"] is True


@pytest.mark.asyncio
async def test_index_single_asset_success(client, db):
    project = await _project(db)
    asset = await _asset(db, project.id)
    await db.commit()
    with patch("services.embedding_service.index_asset", new_callable=AsyncMock, return_value=True):
        r = await client.post(f"/api/embeddings/index_asset/{asset.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["asset_id"] == asset.id


@pytest.mark.asyncio
async def test_index_single_asset_not_found(client):
    """When index_asset returns False, endpoint returns 404."""
    with patch("services.embedding_service.index_asset", new_callable=AsyncMock, return_value=False):
        r = await client.post("/api/embeddings/index_asset/nonexistent-id")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_embedding_status(client, db):
    """GET /api/embeddings/status/{project_id} returns coverage stats."""
    project = await _project(db)
    await db.commit()
    mock_status = {
        "total_assets": 10,
        "analyzed_assets": 5,
        "pending_analysis": 5,
        "qdrant_vectors": 4,
        "coverage_pct": 50.0,
    }
    with patch("services.embedding_service.get_embedding_status", new_callable=AsyncMock, return_value=mock_status):
        r = await client.get(f"/api/embeddings/status/{project.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["total_assets"] == 10
    assert body["coverage_pct"] == 50.0
