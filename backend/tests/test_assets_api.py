"""Tests for assets API endpoints."""
from __future__ import annotations

import pytest
from models.asset import Asset
from models.project import Project


async def _create_project(db, name="test-assets") -> Project:
    project = Project(name=name, description="")
    db.add(project)
    await db.flush()
    return project


async def _create_asset(db, project_id, filename="test.png", **kwargs) -> Asset:
    defaults = dict(
        project_id=project_id,
        filename=filename,
        filepath=f"/tmp/fake/{filename}",
        mime_type="image/png",
        width=512,
        height=512,
    )
    defaults.update(kwargs)
    asset = Asset(**defaults)
    db.add(asset)
    await db.flush()
    return asset


# Tests for list_assets
@pytest.mark.asyncio
async def test_list_assets_empty_project(client, db):
    project = await _create_project(db)
    await db.commit()
    r = await client.get(f"/api/projects/{project.id}/assets")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["items"] == []
    assert body["has_next"] is False


@pytest.mark.asyncio
async def test_list_assets_returns_paginated_results(client, db):
    project = await _create_project(db, "pagination-test")
    for i in range(5):
        await _create_asset(db, project.id, filename=f"img{i}.png", composite_score=float(i))
    await db.commit()
    r = await client.get(f"/api/projects/{project.id}/assets?page=1&page_size=2")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["page"] == 1
    assert body["has_next"] is True


@pytest.mark.asyncio
async def test_list_assets_pagination_last_page(client, db):
    project = await _create_project(db, "last-page")
    for i in range(3):
        await _create_asset(db, project.id, filename=f"last{i}.png")
    await db.commit()
    r = await client.get(f"/api/projects/{project.id}/assets?page=2&page_size=2")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1
    assert body["has_next"] is False


@pytest.mark.asyncio
async def test_list_assets_sort_by_composite_score_asc(client, db):
    project = await _create_project(db, "sort-test")
    await _create_asset(db, project.id, filename="low.png", composite_score=0.1)
    await _create_asset(db, project.id, filename="high.png", composite_score=0.9)
    await db.commit()
    r = await client.get(f"/api/projects/{project.id}/assets?sort_by=composite_score&sort_dir=asc")
    assert r.status_code == 200
    items = r.json()["items"]
    assert items[0]["filename"] == "low.png"
    assert items[1]["filename"] == "high.png"


@pytest.mark.asyncio
async def test_list_assets_filter_min_score(client, db):
    project = await _create_project(db, "min-score-filter")
    await _create_asset(db, project.id, filename="bad.png", composite_score=0.2)
    await _create_asset(db, project.id, filename="good.png", composite_score=0.8)
    await db.commit()
    r = await client.get(f"/api/projects/{project.id}/assets?min_score=0.5")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["filename"] == "good.png"


@pytest.mark.asyncio
async def test_list_assets_filter_review_state(client, db):
    project = await _create_project(db, "review-state-filter")
    await _create_asset(db, project.id, filename="pending.png", review_state="pending")
    await _create_asset(db, project.id, filename="approved.png", review_state="approved")
    await db.commit()
    r = await client.get(f"/api/projects/{project.id}/assets?review_state=approved")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["review_state"] == "approved"


@pytest.mark.asyncio
async def test_list_assets_filter_has_face(client, db):
    project = await _create_project(db, "face-filter")
    await _create_asset(db, project.id, filename="noface.png", face_count=0)
    await _create_asset(db, project.id, filename="face.png", face_count=2)
    await db.commit()
    r = await client.get(f"/api/projects/{project.id}/assets?has_face=true")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["filename"] == "face.png"


@pytest.mark.asyncio
async def test_list_assets_filter_is_flagged(client, db):
    project = await _create_project(db, "flag-filter")
    await _create_asset(db, project.id, filename="normal.png", is_flagged=False)
    await _create_asset(db, project.id, filename="flagged.png", is_flagged=True)
    await db.commit()
    r = await client.get(f"/api/projects/{project.id}/assets?is_flagged=true")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["is_flagged"] is True


@pytest.mark.asyncio
async def test_list_assets_search_by_filename(client, db):
    project = await _create_project(db, "search-filter")
    await _create_asset(db, project.id, filename="photo_cat.png")
    await _create_asset(db, project.id, filename="photo_dog.png")
    await db.commit()
    r = await client.get(f"/api/projects/{project.id}/assets?search=cat")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert "cat" in body["items"][0]["filename"]


# Tests for get_asset
@pytest.mark.asyncio
async def test_get_asset_returns_detail(client, db):
    project = await _create_project(db, "get-detail")
    asset = await _create_asset(db, project.id, filename="detail.png", composite_score=0.75)
    await db.commit()
    r = await client.get(f"/api/assets/{asset.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == asset.id
    assert body["filename"] == "detail.png"
    assert body["composite_score"] == 0.75


@pytest.mark.asyncio
async def test_get_asset_not_found(client):
    r = await client.get("/api/assets/nonexistent-id")
    assert r.status_code == 404


# Tests for update_asset
@pytest.mark.asyncio
async def test_update_asset_shot_type(client, db):
    project = await _create_project(db, "update-test")
    asset = await _create_asset(db, project.id, filename="update.png")
    await db.commit()
    r = await client.patch(f"/api/assets/{asset.id}", json={"shot_type": "closeup"})
    assert r.status_code == 200
    assert r.json()["shot_type"] == "closeup"


@pytest.mark.asyncio
async def test_update_asset_not_found(client):
    r = await client.patch("/api/assets/nonexistent", json={"shot_type": "closeup"})
    assert r.status_code == 404


# Tests for delete_asset
@pytest.mark.asyncio
async def test_delete_asset_success(client, db):
    project = await _create_project(db, "delete-ok")
    asset = await _create_asset(db, project.id, filename="bye.png")
    await db.commit()
    r = await client.delete(f"/api/assets/{asset.id}")
    assert r.status_code == 204
    # Confirm the asset is gone
    r2 = await client.get(f"/api/assets/{asset.id}")
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_delete_asset_not_found(client):
    r = await client.delete("/api/assets/nonexistent")
    assert r.status_code == 404


# Tests for bulk_delete
@pytest.mark.asyncio
async def test_bulk_delete_success(client, db):
    project = await _create_project(db, "bulk-del-ok")
    a1 = await _create_asset(db, project.id, filename="bulk1.png")
    a2 = await _create_asset(db, project.id, filename="bulk2.png")
    await db.commit()
    r = await client.post("/api/assets/bulk-delete", json={"ids": [a1.id, a2.id]})
    assert r.status_code == 200
    assert r.json()["deleted"] == 2


@pytest.mark.asyncio
async def test_bulk_delete_empty_ids_returns_400(client):
    r = await client.post("/api/assets/bulk-delete", json={"ids": []})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_bulk_delete_nonexistent_ids_returns_zero_deleted(client):
    r = await client.post("/api/assets/bulk-delete", json={"ids": ["fake-1", "fake-2"]})
    assert r.status_code == 200
    assert r.json()["deleted"] == 0


# Tests for search_assets
@pytest.mark.asyncio
async def test_search_assets_by_query(client, db):
    project = await _create_project(db, "search-api")
    await _create_asset(db, project.id, filename="sunset.png")
    await _create_asset(db, project.id, filename="mountain.png")
    await db.commit()
    r = await client.get(f"/api/projects/{project.id}/assets/search?q=sunset")
    assert r.status_code == 200
    body = r.json()
    assert len(body["assets"]) == 1
    assert "sunset" in body["assets"][0]["filename"]


# Tests for flat search
@pytest.mark.asyncio
async def test_search_assets_flat(client, db):
    project = await _create_project(db, "flat-search")
    await _create_asset(db, project.id, filename="flat1.png", review_state="approved")
    await _create_asset(db, project.id, filename="flat2.png", review_state="rejected")
    await db.commit()
    r = await client.get(f"/api/assets/search?project_id={project.id}&review_state=approved")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["review_state"] == "approved"
