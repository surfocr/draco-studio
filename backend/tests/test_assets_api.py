"""
Tests for the assets REST API.

Covers:
- GET /api/projects/{project_id}/assets with filters (score, review_state, has_face,
  is_flagged, is_rejected, has_caption, has_duplicate, search)
- GET /api/projects/{project_id}/assets/search
- GET /api/assets/{asset_id}
- PATCH /api/assets/{asset_id}
"""
from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.asset import Asset
from models.caption import CaptionVersion
from models.project import Project


# ── Shared helpers ─────────────────────────────────────────────────────────────

async def _create_project(db: AsyncSession, name: str = "assets-api") -> Project:
    project = Project(name=name, description="")
    db.add(project)
    await db.flush()
    return project


async def _create_asset(
    db: AsyncSession,
    project_id: str,
    filename: str,
    *,
    composite_score: float = 0.8,
    face_count: int = 0,
    review_state: str = "pending",
    is_flagged: bool = False,
    is_rejected: bool = False,
    shot_type: str = "close_up",
) -> Asset:
    asset = Asset(
        project_id=project_id,
        filename=filename,
        filepath=f"/tmp/{filename}",
        mime_type="image/png",
        width=512,
        height=512,
        composite_score=composite_score,
        face_count=face_count,
        review_state=review_state,
        is_flagged=is_flagged,
        is_rejected=is_rejected,
        shot_type=shot_type,
    )
    db.add(asset)
    await db.flush()
    return asset


async def _attach_caption(db: AsyncSession, asset: Asset, text: str = "test caption") -> CaptionVersion:
    caption = CaptionVersion(
        asset_id=asset.id,
        text=text,
        style="natural",
        provider="test",
        model="test",
        is_active=True,
    )
    db.add(caption)
    await db.flush()
    asset.active_caption_id = caption.id
    await db.flush()
    return caption


@asynccontextmanager
async def _client_for_db(db: AsyncSession):
    from main import app

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


# ── Tests: list assets ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_assets_returns_empty_for_new_project(db):
    project = await _create_project(db, "empty-assets")
    async with _client_for_db(db) as client:
        r = await client.get(f"/api/projects/{project.id}/assets")
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0
    assert body["has_next"] is False


@pytest.mark.asyncio
async def test_list_assets_returns_all_project_assets(db):
    project = await _create_project(db, "list-all")
    await _create_asset(db, project.id, "a.png")
    await _create_asset(db, project.id, "b.png")
    await _create_asset(db, project.id, "c.png")

    async with _client_for_db(db) as client:
        r = await client.get(f"/api/projects/{project.id}/assets")

    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3
    assert len(body["items"]) == 3


@pytest.mark.asyncio
async def test_list_assets_filters_by_min_score(db):
    project = await _create_project(db, "min-score")
    await _create_asset(db, project.id, "low.png", composite_score=0.3)
    await _create_asset(db, project.id, "high.png", composite_score=0.9)

    async with _client_for_db(db) as client:
        r = await client.get(f"/api/projects/{project.id}/assets?min_score=0.5")

    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["filename"] == "high.png"


@pytest.mark.asyncio
async def test_list_assets_filters_by_max_score(db):
    project = await _create_project(db, "max-score")
    await _create_asset(db, project.id, "low.png", composite_score=0.2)
    await _create_asset(db, project.id, "high.png", composite_score=0.95)

    async with _client_for_db(db) as client:
        r = await client.get(f"/api/projects/{project.id}/assets?max_score=0.5")

    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["filename"] == "low.png"


@pytest.mark.asyncio
async def test_list_assets_filters_by_review_state(db):
    project = await _create_project(db, "review-state")
    await _create_asset(db, project.id, "pending.png", review_state="pending")
    await _create_asset(db, project.id, "approved.png", review_state="approved")

    async with _client_for_db(db) as client:
        r = await client.get(f"/api/projects/{project.id}/assets?review_state=approved")

    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["filename"] == "approved.png"


@pytest.mark.asyncio
async def test_list_assets_filters_by_is_flagged(db):
    project = await _create_project(db, "flagged-filter")
    await _create_asset(db, project.id, "normal.png")
    await _create_asset(db, project.id, "flagged.png", is_flagged=True)

    async with _client_for_db(db) as client:
        r = await client.get(f"/api/projects/{project.id}/assets?is_flagged=true")

    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["is_flagged"] is True


@pytest.mark.asyncio
async def test_list_assets_filters_by_has_face(db):
    project = await _create_project(db, "has-face")
    await _create_asset(db, project.id, "no-face.png", face_count=0)
    await _create_asset(db, project.id, "with-face.png", face_count=1)

    async with _client_for_db(db) as client:
        r_faces = await client.get(f"/api/projects/{project.id}/assets?has_face=true")
        r_no_faces = await client.get(f"/api/projects/{project.id}/assets?has_face=false")

    assert len(r_faces.json()["items"]) == 1
    assert r_faces.json()["items"][0]["filename"] == "with-face.png"

    assert len(r_no_faces.json()["items"]) == 1
    assert r_no_faces.json()["items"][0]["filename"] == "no-face.png"


@pytest.mark.asyncio
async def test_list_assets_filters_by_has_caption(db):
    project = await _create_project(db, "has-caption")
    uncaptioned = await _create_asset(db, project.id, "no-cap.png")
    captioned = await _create_asset(db, project.id, "cap.png")
    await _attach_caption(db, captioned)

    async with _client_for_db(db) as client:
        r = await client.get(f"/api/projects/{project.id}/assets?has_caption=true")

    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == captioned.id


@pytest.mark.asyncio
async def test_list_assets_filters_by_filename_search(db):
    project = await _create_project(db, "search-filter")
    await _create_asset(db, project.id, "portrait_001.png")
    await _create_asset(db, project.id, "landscape_002.png")
    await _create_asset(db, project.id, "portrait_003.png")

    async with _client_for_db(db) as client:
        r = await client.get(f"/api/projects/{project.id}/assets?search=portrait")

    assert r.status_code == 200
    items = r.json()["items"]
    assert len(items) == 2
    assert all("portrait" in item["filename"] for item in items)


@pytest.mark.asyncio
async def test_list_assets_pagination(db):
    project = await _create_project(db, "pagination")
    for i in range(5):
        await _create_asset(db, project.id, f"img_{i:02d}.png")

    async with _client_for_db(db) as client:
        page1 = await client.get(f"/api/projects/{project.id}/assets?page=1&page_size=2")
        page2 = await client.get(f"/api/projects/{project.id}/assets?page=2&page_size=2")

    assert page1.status_code == 200
    assert page2.status_code == 200

    page1_ids = [item["id"] for item in page1.json()["items"]]
    page2_ids = [item["id"] for item in page2.json()["items"]]

    assert len(page1_ids) == 2
    assert len(page2_ids) == 2
    assert set(page1_ids).isdisjoint(page2_ids)
    assert page1.json()["has_next"] is True
    assert page1.json()["total"] == 5


# ── Tests: get asset ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_asset_returns_detail(db):
    project = await _create_project(db, "get-asset")
    asset = await _create_asset(db, project.id, "detail.png", composite_score=0.77)

    async with _client_for_db(db) as client:
        r = await client.get(f"/api/assets/{asset.id}")

    assert r.status_code == 200
    body = r.json()
    assert body["id"] == asset.id
    assert body["filename"] == "detail.png"
    assert body["composite_score"] == pytest.approx(0.77, abs=0.001)


@pytest.mark.asyncio
async def test_get_asset_returns_404_for_unknown_id(client):
    r = await client.get("/api/assets/nonexistent-id-xyz")
    assert r.status_code == 404


# ── Tests: update asset ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_patch_asset_updates_review_state(db):
    project = await _create_project(db, "patch-review")
    asset = await _create_asset(db, project.id, "patch.png")

    async with _client_for_db(db) as client:
        r = await client.patch(f"/api/assets/{asset.id}", json={"review_state": "approved"})

    assert r.status_code == 200
    assert r.json()["review_state"] == "approved"


@pytest.mark.asyncio
async def test_patch_asset_updates_is_flagged(db):
    project = await _create_project(db, "patch-flag")
    asset = await _create_asset(db, project.id, "flag.png")

    async with _client_for_db(db) as client:
        r = await client.patch(f"/api/assets/{asset.id}", json={"is_flagged": True})

    assert r.status_code == 200
    assert r.json()["is_flagged"] is True


@pytest.mark.asyncio
async def test_patch_asset_returns_404_for_unknown_id(client):
    r = await client.patch("/api/assets/nonexistent", json={"review_state": "approved"})
    assert r.status_code == 404


# ── Tests: search assets ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_search_assets_returns_matching_filenames(db):
    project = await _create_project(db, "search-api")
    await _create_asset(db, project.id, "alpha_001.png")
    await _create_asset(db, project.id, "beta_001.png")
    await _create_asset(db, project.id, "alpha_002.png")

    async with _client_for_db(db) as client:
        r = await client.get(f"/api/projects/{project.id}/assets/search?q=alpha")

    assert r.status_code == 200
    body = r.json()
    assert "assets" in body
    assert len(body["assets"]) == 2
    assert all("alpha" in a["filename"] for a in body["assets"])


@pytest.mark.asyncio
async def test_search_assets_filters_by_min_score(db):
    project = await _create_project(db, "search-score")
    await _create_asset(db, project.id, "low.png", composite_score=0.1)
    await _create_asset(db, project.id, "high.png", composite_score=0.9)

    async with _client_for_db(db) as client:
        r = await client.get(f"/api/projects/{project.id}/assets/search?min_score=0.5")

    assert r.status_code == 200
    assets = r.json()["assets"]
    assert len(assets) == 1
    assert assets[0]["filename"] == "high.png"


@pytest.mark.asyncio
async def test_search_assets_filters_by_review_state(db):
    project = await _create_project(db, "search-review")
    await _create_asset(db, project.id, "pending.png", review_state="pending")
    await _create_asset(db, project.id, "approved.png", review_state="approved")

    async with _client_for_db(db) as client:
        r = await client.get(f"/api/projects/{project.id}/assets/search?review_state=approved")

    assert r.status_code == 200
    assert len(r.json()["assets"]) == 1
    assert r.json()["assets"][0]["review_state"] == "approved"
