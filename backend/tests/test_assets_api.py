"""Tests for the Assets API endpoints."""
from __future__ import annotations

import pytest

from models.asset import Asset
from models.project import Project


async def _create_project_with_assets(db, n=3, project_name="test-assets"):
    project = Project(name=project_name, description="")
    db.add(project)
    await db.flush()
    assets = []
    for i in range(n):
        asset = Asset(
            project_id=project.id,
            filename=f"image_{i}.png",
            filepath=f"/data/dataset/image_{i}.png",
            mime_type="image/png",
            width=512,
            height=512,
            composite_score=0.5 + i * 0.1,
            face_count=i,
            review_state="pending",
        )
        db.add(asset)
        assets.append(asset)
    await db.flush()
    return project, assets


# ── GET /api/projects/{project_id}/assets  (list_assets) ─────────────────────


@pytest.mark.asyncio
async def test_list_assets_basic(client):
    """Basic listing returns paginated response structure."""
    r = await client.post("/api/projects", json={"name": "list-basic", "description": ""})
    project_id = r.json()["id"]

    r = await client.get(f"/api/projects/{project_id}/assets")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "page_size" in body
    assert "has_next" in body
    assert body["page"] == 1
    assert isinstance(body["items"], list)


@pytest.mark.asyncio
async def test_list_assets_returns_created(client, db):
    """Listing assets returns assets that were created."""
    project, assets = await _create_project_with_assets(db, n=3, project_name="list-created")
    await db.commit()

    r = await client.get(f"/api/projects/{project.id}/assets")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3


@pytest.mark.asyncio
async def test_list_assets_filter_min_score(client, db):
    """Filtering by min_score returns only qualifying assets."""
    project, assets = await _create_project_with_assets(db, n=3, project_name="filter-min")
    await db.commit()

    r = await client.get(f"/api/projects/{project.id}/assets", params={"min_score": 0.65})
    assert r.status_code == 200
    body = r.json()
    for item in body["items"]:
        assert item["composite_score"] >= 0.65


@pytest.mark.asyncio
async def test_list_assets_filter_max_score(client, db):
    """Filtering by max_score returns only qualifying assets."""
    project, assets = await _create_project_with_assets(db, n=3, project_name="filter-max")
    await db.commit()

    r = await client.get(f"/api/projects/{project.id}/assets", params={"max_score": 0.55})
    assert r.status_code == 200
    body = r.json()
    for item in body["items"]:
        assert item["composite_score"] <= 0.55


@pytest.mark.asyncio
async def test_list_assets_filter_review_state(client, db):
    """Filtering by review_state returns matching assets."""
    project, assets = await _create_project_with_assets(db, n=2, project_name="filter-review")
    assets[0].review_state = "approved"
    await db.commit()

    r = await client.get(
        f"/api/projects/{project.id}/assets", params={"review_state": "approved"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["review_state"] == "approved"


@pytest.mark.asyncio
async def test_list_assets_filter_has_face(client, db):
    """Filtering by has_face=true returns assets with face_count > 0."""
    project, assets = await _create_project_with_assets(db, n=3, project_name="filter-face")
    await db.commit()

    r = await client.get(
        f"/api/projects/{project.id}/assets", params={"has_face": "true"}
    )
    assert r.status_code == 200
    body = r.json()
    for item in body["items"]:
        assert item["face_count"] > 0


@pytest.mark.asyncio
async def test_list_assets_filter_has_face_false(client, db):
    """Filtering by has_face=false returns assets with face_count == 0."""
    project, assets = await _create_project_with_assets(db, n=3, project_name="filter-noface")
    await db.commit()

    r = await client.get(
        f"/api/projects/{project.id}/assets", params={"has_face": "false"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    for item in body["items"]:
        assert item["face_count"] == 0


@pytest.mark.asyncio
async def test_list_assets_sort_by_composite_score(client, db):
    """Sorting by composite_score asc returns lowest first."""
    project, assets = await _create_project_with_assets(db, n=3, project_name="sort-score")
    await db.commit()

    r = await client.get(
        f"/api/projects/{project.id}/assets",
        params={"sort_by": "composite_score", "sort_dir": "asc"},
    )
    assert r.status_code == 200
    scores = [item["composite_score"] for item in r.json()["items"]]
    assert scores == sorted(scores)


@pytest.mark.asyncio
async def test_list_assets_sort_by_filename(client, db):
    """Sorting by filename asc returns alphabetical order."""
    project, assets = await _create_project_with_assets(db, n=3, project_name="sort-name")
    await db.commit()

    r = await client.get(
        f"/api/projects/{project.id}/assets",
        params={"sort_by": "filename", "sort_dir": "asc"},
    )
    assert r.status_code == 200
    filenames = [item["filename"] for item in r.json()["items"]]
    assert filenames == sorted(filenames)


@pytest.mark.asyncio
async def test_list_assets_pagination(client, db):
    """Pagination returns correct page and page_size."""
    project, _ = await _create_project_with_assets(db, n=5, project_name="paginate")
    await db.commit()

    r = await client.get(
        f"/api/projects/{project.id}/assets", params={"page": 1, "page_size": 2}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert len(body["items"]) == 2
    assert body["has_next"] is True

    r2 = await client.get(
        f"/api/projects/{project.id}/assets", params={"page": 3, "page_size": 2}
    )
    body2 = r2.json()
    assert body2["page"] == 3
    assert len(body2["items"]) == 1
    assert body2["has_next"] is False


@pytest.mark.asyncio
async def test_list_assets_search_filename(client, db):
    """Search param filters by filename substring."""
    project, assets = await _create_project_with_assets(db, n=3, project_name="search-fn")
    await db.commit()

    r = await client.get(
        f"/api/projects/{project.id}/assets", params={"search": "image_1"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["filename"] == "image_1.png"


# ── GET /api/assets/{asset_id}  (get_asset) ──────────────────────────────────


@pytest.mark.asyncio
async def test_get_asset_detail(client, db):
    """Returns full asset detail for an existing asset."""
    project, assets = await _create_project_with_assets(db, n=1, project_name="get-detail")
    await db.commit()

    asset_id = assets[0].id
    r = await client.get(f"/api/assets/{asset_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == asset_id
    assert body["filename"] == "image_0.png"
    assert body["width"] == 512
    assert body["height"] == 512
    assert "filepath" in body
    assert "mime_type" in body


@pytest.mark.asyncio
async def test_get_asset_not_found(client):
    """Returns 404 for a nonexistent asset id."""
    r = await client.get("/api/assets/nonexistent-id-12345")
    assert r.status_code == 404


# ── PATCH /api/assets/{asset_id}  (update_asset) ─────────────────────────────


@pytest.mark.asyncio
async def test_update_asset_shot_type(client, db):
    """Updating shot_type persists the change."""
    project, assets = await _create_project_with_assets(db, n=1, project_name="upd-shot")
    await db.commit()

    asset_id = assets[0].id
    r = await client.patch(f"/api/assets/{asset_id}", json={"shot_type": "closeup"})
    assert r.status_code == 200
    assert r.json()["shot_type"] == "closeup"


@pytest.mark.asyncio
async def test_update_asset_review_state(client, db):
    """Updating review_state persists the change."""
    project, assets = await _create_project_with_assets(db, n=1, project_name="upd-review")
    await db.commit()

    asset_id = assets[0].id
    r = await client.patch(f"/api/assets/{asset_id}", json={"review_state": "approved"})
    assert r.status_code == 200
    assert r.json()["review_state"] == "approved"


@pytest.mark.asyncio
async def test_update_asset_is_flagged(client, db):
    """Updating is_flagged persists the change."""
    project, assets = await _create_project_with_assets(db, n=1, project_name="upd-flag")
    await db.commit()

    asset_id = assets[0].id
    r = await client.patch(f"/api/assets/{asset_id}", json={"is_flagged": True})
    assert r.status_code == 200
    assert r.json()["is_flagged"] is True


# ── DELETE /api/assets/{asset_id}  (delete_asset) ────────────────────────────


@pytest.mark.asyncio
async def test_delete_asset(client, db):
    """Deleting an existing asset returns 204."""
    project, assets = await _create_project_with_assets(db, n=1, project_name="del-one")
    await db.commit()

    asset_id = assets[0].id
    r = await client.delete(f"/api/assets/{asset_id}")
    assert r.status_code == 204

    # Confirm it is gone
    r2 = await client.get(f"/api/assets/{asset_id}")
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_delete_asset_not_found(client):
    """Deleting a nonexistent asset returns 404."""
    r = await client.delete("/api/assets/nonexistent-id-99999")
    assert r.status_code == 404


# ── POST /api/assets/bulk-delete  (bulk_delete_assets) ───────────────────────


@pytest.mark.asyncio
async def test_bulk_delete_assets(client, db):
    """Bulk deleting multiple assets removes them."""
    project, assets = await _create_project_with_assets(db, n=3, project_name="bulk-del")
    await db.commit()

    ids = [a.id for a in assets[:2]]
    r = await client.post("/api/assets/bulk-delete", json={"ids": ids})
    assert r.status_code == 200
    body = r.json()
    assert body["deleted"] == 2

    # Confirm deleted assets are gone, remaining one is still there
    r2 = await client.get(f"/api/assets/{ids[0]}")
    assert r2.status_code == 404
    r3 = await client.get(f"/api/assets/{assets[2].id}")
    assert r3.status_code == 200


@pytest.mark.asyncio
async def test_bulk_delete_empty_ids(client):
    """Bulk delete with empty ids list returns 400."""
    r = await client.post("/api/assets/bulk-delete", json={"ids": []})
    assert r.status_code == 400


# ── GET /api/projects/{project_id}/assets/search  (search_assets) ────────────


@pytest.mark.asyncio
async def test_search_assets_by_filename(client, db):
    """Search endpoint returns assets matching filename query."""
    project, assets = await _create_project_with_assets(db, n=3, project_name="search-q")
    await db.commit()

    r = await client.get(
        f"/api/projects/{project.id}/assets/search", params={"q": "image_2"}
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body["assets"]) == 1
    assert body["assets"][0]["filename"] == "image_2.png"


@pytest.mark.asyncio
async def test_search_assets_with_filter(client, db):
    """Search endpoint respects min_score filter."""
    project, assets = await _create_project_with_assets(db, n=3, project_name="search-filter")
    await db.commit()

    r = await client.get(
        f"/api/projects/{project.id}/assets/search", params={"min_score": 0.65}
    )
    assert r.status_code == 200
    body = r.json()
    for item in body["assets"]:
        assert item["composite_score"] >= 0.65


# ── GET /api/assets/search  (search_assets_flat) ────────────────────────────


@pytest.mark.asyncio
async def test_search_assets_flat(client, db):
    """Flat search endpoint returns list of assets for the given project_id."""
    project, assets = await _create_project_with_assets(db, n=2, project_name="flat-search")
    await db.commit()

    r = await client.get("/api/assets/search", params={"project_id": project.id})
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) == 2
    assert body[0]["id"] in [a.id for a in assets]


@pytest.mark.asyncio
async def test_search_assets_flat_with_filter(client, db):
    """Flat search respects review_state filter."""
    project, assets = await _create_project_with_assets(db, n=2, project_name="flat-filter")
    assets[0].review_state = "approved"
    await db.commit()

    r = await client.get(
        "/api/assets/search",
        params={"project_id": project.id, "review_state": "approved"},
    )
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 1
    assert body[0]["review_state"] == "approved"


# ── GET /api/assets/{asset_id}/explain  (explain_asset_score) ────────────────


@pytest.mark.asyncio
async def test_explain_asset_score(client, db):
    """Explain endpoint returns score breakdown dict."""
    project, assets = await _create_project_with_assets(db, n=1, project_name="explain")
    assets[0].technical_quality = 0.8
    assets[0].aesthetic_score = 0.7
    assets[0].face_quality = 0.6
    await db.commit()

    asset_id = assets[0].id
    r = await client.get(f"/api/assets/{asset_id}/explain")
    assert r.status_code == 200
    body = r.json()
    assert "composite" in body
    assert "dimensions" in body
    assert isinstance(body["dimensions"], list)
    assert len(body["dimensions"]) >= 1


@pytest.mark.asyncio
async def test_explain_asset_not_found(client):
    """Explain endpoint returns 404 for nonexistent asset."""
    r = await client.get("/api/assets/nonexistent-id-00000/explain")
    assert r.status_code == 404
