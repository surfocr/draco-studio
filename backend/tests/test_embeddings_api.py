"""Embedding indexing and status API tests."""
from __future__ import annotations

import pytest

from models.project import Project


@pytest.mark.asyncio
async def test_index_project_returns_queued(client):
    """POST /api/embeddings/index returns queued status immediately."""
    r = await client.post("/api/embeddings/index", json={
        "project_id": "proj-123",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "queued"
    assert body["project_id"] == "proj-123"
    assert body["force"] is False


@pytest.mark.asyncio
async def test_index_single_asset_not_found(client):
    """POST /api/embeddings/index_asset/{id} returns 404 for nonexistent asset."""
    r = await client.post(
        "/api/embeddings/index_asset/00000000-0000-0000-0000-000000000000"
    )
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_embedding_status_empty_project(client, db):
    """GET /api/embeddings/status/{id} returns zeros for a project with no assets."""
    project = Project(name="embed-test", description="")
    db.add(project)
    await db.commit()

    r = await client.get(f"/api/embeddings/status/{project.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["total_assets"] == 0
    assert body["analyzed_assets"] == 0
    assert body["pending_analysis"] == 0
    assert body["coverage_pct"] == 0.0
