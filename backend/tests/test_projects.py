"""Project CRUD smoke tests."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_create_project(client):
    """POST /api/projects creates a project and returns it."""
    r = await client.post("/api/projects", json={
        "name": "Test Project",
        "description": "A test project",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Test Project"
    assert "id" in body
    assert body["asset_count"] == 0


@pytest.mark.asyncio
async def test_list_projects(client):
    """GET /api/projects returns a list."""
    # Create a project first
    await client.post("/api/projects", json={"name": "List Test", "description": ""})

    r = await client.get("/api/projects")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) >= 1


@pytest.mark.asyncio
async def test_get_project(client):
    """GET /api/projects/{id} returns project details."""
    r = await client.post("/api/projects", json={"name": "Get Test", "description": ""})
    project_id = r.json()["id"]

    r = await client.get(f"/api/projects/{project_id}")
    assert r.status_code == 200
    assert r.json()["id"] == project_id
    assert r.json()["name"] == "Get Test"


@pytest.mark.asyncio
async def test_get_project_stats(client):
    """GET /api/projects/{id}/stats returns stats dict."""
    r = await client.post("/api/projects", json={"name": "Stats Test", "description": ""})
    project_id = r.json()["id"]

    r = await client.get(f"/api/projects/{project_id}/stats")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert "approved" in body
    assert "captioned" in body


@pytest.mark.asyncio
async def test_get_preferences(client):
    """GET /api/preferences returns default preferences."""
    r = await client.get("/api/preferences")
    assert r.status_code == 200
    body = r.json()
    assert body["theme"] == "dark"
    assert body["gallery_zoom"] == 1
    assert body["auto_analyze_on_import"] is True


@pytest.mark.asyncio
async def test_update_preferences(client):
    """PATCH /api/preferences updates selected fields."""
    r = await client.patch("/api/preferences", json={"theme": "light", "gallery_zoom": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["theme"] == "light"
    assert body["gallery_zoom"] == 2
    # Other fields should keep defaults
    assert body["auto_analyze_on_import"] is True


@pytest.mark.asyncio
async def test_project_runtime_defaults(client):
    create = await client.post("/api/projects", json={"name": "Runtime Defaults"})
    project_id = create.json()["id"]

    r = await client.get(f"/api/projects/{project_id}/runtime")
    assert r.status_code == 200
    body = r.json()
    assert body["project_id"] == project_id
    assert body["runtime_mode"] == "local"
    assert "caption" in body["task_provider_options"]
    assert any(task["task_key"] == "caption" for task in body["task_catalog"])


@pytest.mark.asyncio
async def test_project_runtime_update(client):
    create = await client.post("/api/projects", json={"name": "Runtime Update"})
    project_id = create.json()["id"]

    r = await client.patch(
        f"/api/projects/{project_id}/runtime",
        json={
            "runtime_mode": "hybrid",
            "task_provider_overrides": {
                "caption": "ollama",
                "ranking_explanation": "gemini",
            },
            "task_provider_options": {
                "caption": {
                    "model": "moondream",
                    "temperature": 0.15,
                }
            },
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["runtime_mode"] == "hybrid"
    assert body["task_provider_overrides"]["caption"] == "ollama"
    assert body["task_provider_options"]["caption"]["model"] == "moondream"
