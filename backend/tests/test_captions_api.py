"""Tests for captions API endpoints."""
from __future__ import annotations

import pytest
from models.asset import Asset
from models.caption import CaptionVersion
from models.project import Project


async def _project(db, name="captions-test") -> Project:
    p = Project(name=name, description="")
    db.add(p)
    await db.flush()
    return p


async def _asset(db, project_id, filename="cap.png", active_caption_id=None) -> Asset:
    a = Asset(
        project_id=project_id,
        filename=filename,
        filepath=f"/tmp/fake/{filename}",
        mime_type="image/png",
        width=512, height=512,
        active_caption_id=active_caption_id,
    )
    db.add(a)
    await db.flush()
    return a


async def _caption(db, asset_id, text="A test caption", provider="test", is_active=False, **kwargs) -> CaptionVersion:
    cv = CaptionVersion(
        asset_id=asset_id,
        text=text,
        style="natural",
        provider=provider,
        is_active=is_active,
        **kwargs,
    )
    db.add(cv)
    await db.flush()
    return cv


@pytest.mark.asyncio
async def test_list_captions_empty(client, db):
    project = await _project(db)
    asset = await _asset(db, project.id)
    await db.commit()
    r = await client.get(f"/api/assets/{asset.id}/captions")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_captions_returns_versions(client, db):
    project = await _project(db)
    asset = await _asset(db, project.id)
    c1 = await _caption(db, asset.id, text="First caption", provider="ollama")
    c2 = await _caption(db, asset.id, text="Second caption", provider="gemini")
    await db.commit()
    r = await client.get(f"/api/assets/{asset.id}/captions")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    texts = {c["text"] for c in body}
    assert "First caption" in texts
    assert "Second caption" in texts


@pytest.mark.asyncio
async def test_activate_caption(client, db):
    project = await _project(db)
    asset = await _asset(db, project.id)
    cap = await _caption(db, asset.id, text="Activate me", is_active=False)
    await db.commit()
    r = await client.put(f"/api/captions/{cap.id}/activate")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["version_id"] == cap.id


@pytest.mark.asyncio
async def test_activate_caption_not_found(client):
    r = await client.put("/api/captions/nonexistent/activate")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_delete_caption_not_found(client):
    r = await client.delete("/api/captions/nonexistent")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_edit_caption_not_found(client):
    r = await client.post("/api/captions/nonexistent/edit", json={"text": "new text"})
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_bulk_prepend_rejects_missing_prefix(client):
    r = await client.post("/api/captions/bulk_prepend", json={"asset_ids": ["a1"], "prefix": ""})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_bulk_prepend_rejects_missing_asset_ids(client):
    r = await client.post("/api/captions/bulk_prepend", json={"asset_ids": [], "prefix": "hello"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_bulk_append_rejects_missing_suffix(client):
    r = await client.post("/api/captions/bulk_append", json={"asset_ids": ["a1"], "suffix": ""})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_bulk_replace_rejects_missing_find(client):
    r = await client.post("/api/captions/bulk_replace", json={"asset_ids": ["a1"], "find": None, "replace": "x"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_bulk_edit_unknown_operation(client, db):
    project = await _project(db)
    asset = await _asset(db, project.id)
    await db.commit()
    r = await client.post(
        f"/api/projects/{project.id}/captions/bulk-edit",
        json={"asset_ids": [asset.id], "operation": "invalid_op"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_bulk_edit_prepend_requires_text(client, db):
    project = await _project(db)
    asset = await _asset(db, project.id)
    await db.commit()
    r = await client.post(
        f"/api/projects/{project.id}/captions/bulk-edit",
        json={"asset_ids": [asset.id], "operation": "prepend"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_bulk_prepend_modifies_active_caption(client, db):
    project = await _project(db)
    asset = await _asset(db, project.id)
    cap = await _caption(db, asset.id, text="Original text", is_active=True)
    asset.active_caption_id = cap.id
    await db.flush()
    await db.commit()
    r = await client.post("/api/captions/bulk_prepend", json={
        "asset_ids": [asset.id],
        "prefix": "PREFIX: ",
    })
    assert r.status_code == 200
    assert r.json()["updated"] >= 0


@pytest.mark.asyncio
async def test_bulk_append_modifies_active_caption(client, db):
    project = await _project(db)
    asset = await _asset(db, project.id)
    cap = await _caption(db, asset.id, text="Original text", is_active=True)
    asset.active_caption_id = cap.id
    await db.flush()
    await db.commit()
    r = await client.post("/api/captions/bulk_append", json={
        "asset_ids": [asset.id],
        "suffix": " SUFFIX",
    })
    assert r.status_code == 200
    assert r.json()["updated"] >= 0
