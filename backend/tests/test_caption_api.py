"""
Tests for the captions REST API and CaptionService.

Covers:
- GET  /api/assets/{asset_id}/captions
- POST /api/captions/{version_id}/edit
- PUT  /api/captions/{version_id}/activate
- DELETE /api/captions/{version_id}
- POST /api/captions/bulk_prepend
- POST /api/captions/bulk_append
- POST /api/captions/bulk_replace
- GET  /api/projects/{project_id}/captions/consistency
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
from services.caption import CaptionService


# ── Shared helpers ─────────────────────────────────────────────────────────────

async def _create_project(db: AsyncSession, name: str = "caption-api") -> Project:
    project = Project(name=name, description="")
    db.add(project)
    await db.flush()
    return project


async def _create_asset(db: AsyncSession, project_id: str, filename: str = "img.png") -> Asset:
    asset = Asset(
        project_id=project_id,
        filename=filename,
        filepath=f"/tmp/{filename}",
        mime_type="image/png",
        width=512,
        height=512,
    )
    db.add(asset)
    await db.flush()
    return asset


async def _create_caption(
    db: AsyncSession,
    asset_id: str,
    text: str,
    *,
    is_active: bool = True,
    style: str = "natural",
) -> CaptionVersion:
    caption = CaptionVersion(
        asset_id=asset_id,
        text=text,
        style=style,
        provider="test",
        model="test-model",
        is_active=is_active,
    )
    db.add(caption)
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


# ── Tests: list caption versions ───────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_captions_returns_empty_for_asset_with_no_captions(db):
    project = await _create_project(db, "list-empty-captions")
    asset = await _create_asset(db, project.id)

    async with _client_for_db(db) as client:
        r = await client.get(f"/api/assets/{asset.id}/captions")

    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_captions_returns_all_versions(db):
    project = await _create_project(db, "list-captions-versions")
    asset = await _create_asset(db, project.id)
    await _create_caption(db, asset.id, "first version", is_active=False)
    await _create_caption(db, asset.id, "second version", is_active=True)

    async with _client_for_db(db) as client:
        r = await client.get(f"/api/assets/{asset.id}/captions")

    assert r.status_code == 200
    versions = r.json()
    assert len(versions) == 2
    active = [v for v in versions if v["is_active"]]
    assert len(active) == 1
    assert active[0]["text"] == "second version"


# ── Tests: edit caption ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_edit_caption_creates_new_version(db):
    project = await _create_project(db, "edit-caption")
    asset = await _create_asset(db, project.id)
    caption = await _create_caption(db, asset.id, "original text")
    asset.active_caption_id = caption.id
    await db.flush()

    async with _client_for_db(db) as client:
        r = await client.post(
            f"/api/captions/{caption.id}/edit",
            json={"text": "edited text", "author": "human"},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "edited text"
    assert body["is_active"] is True
    assert body["is_edited"] is True


@pytest.mark.asyncio
async def test_edit_caption_returns_404_for_missing_version(client):
    r = await client.post(
        "/api/captions/nonexistent-version",
        json={"text": "anything"},
    )
    assert r.status_code in (404, 405)


# ── Tests: activate caption ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_activate_caption_makes_version_active(db):
    project = await _create_project(db, "activate-caption")
    asset = await _create_asset(db, project.id)
    old_active = await _create_caption(db, asset.id, "old caption", is_active=True)
    new_version = await _create_caption(db, asset.id, "new caption", is_active=False)
    asset.active_caption_id = old_active.id
    await db.flush()

    async with _client_for_db(db) as client:
        r = await client.put(f"/api/captions/{new_version.id}/activate")

    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["version_id"] == new_version.id


@pytest.mark.asyncio
async def test_activate_caption_returns_404_for_missing_version(client):
    r = await client.put("/api/captions/nonexistent-version/activate")
    assert r.status_code == 404


# ── Tests: delete caption version ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_inactive_caption_succeeds(db):
    project = await _create_project(db, "delete-caption")
    asset = await _create_asset(db, project.id)
    active = await _create_caption(db, asset.id, "active", is_active=True)
    inactive = await _create_caption(db, asset.id, "inactive", is_active=False)
    asset.active_caption_id = active.id
    await db.flush()

    async with _client_for_db(db) as client:
        r = await client.delete(f"/api/captions/{inactive.id}")

    assert r.status_code == 204


@pytest.mark.asyncio
async def test_delete_active_caption_returns_conflict(db):
    project = await _create_project(db, "delete-active-caption")
    asset = await _create_asset(db, project.id)
    active = await _create_caption(db, asset.id, "active version", is_active=True)
    asset.active_caption_id = active.id
    await db.flush()

    async with _client_for_db(db) as client:
        r = await client.delete(f"/api/captions/{active.id}")

    assert r.status_code == 409


# ── Tests: bulk prepend ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bulk_prepend_adds_text_to_the_front_of_captions(db):
    project = await _create_project(db, "bulk-prepend")
    asset_a = await _create_asset(db, project.id, "a.png")
    asset_b = await _create_asset(db, project.id, "b.png")
    await _create_caption(db, asset_a.id, "portrait of a woman")
    await _create_caption(db, asset_b.id, "portrait of a man")

    async with _client_for_db(db) as client:
        r = await client.post(
            "/api/captions/bulk_prepend",
            json={"asset_ids": [asset_a.id, asset_b.id], "prefix": "ohwx person,"},
        )

    assert r.status_code == 200
    assert r.json()["updated"] == 2

    svc = CaptionService()
    versions_a = await svc.list_versions(asset_a.id, db)
    active_a = next((v for v in versions_a if v.is_active), None)
    assert active_a is not None
    assert active_a.text.startswith("ohwx person,")


@pytest.mark.asyncio
async def test_bulk_prepend_returns_400_when_prefix_is_missing(db):
    project = await _create_project(db, "bulk-prepend-missing")
    asset = await _create_asset(db, project.id)

    async with _client_for_db(db) as client:
        r = await client.post(
            "/api/captions/bulk_prepend",
            json={"asset_ids": [asset.id], "prefix": ""},
        )

    assert r.status_code == 400


# ── Tests: bulk append ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bulk_append_adds_text_to_the_end_of_captions(db):
    project = await _create_project(db, "bulk-append")
    asset = await _create_asset(db, project.id)
    await _create_caption(db, asset.id, "portrait of a woman")

    async with _client_for_db(db) as client:
        r = await client.post(
            "/api/captions/bulk_append",
            json={"asset_ids": [asset.id], "suffix": "studio lighting"},
        )

    assert r.status_code == 200
    assert r.json()["updated"] == 1

    svc = CaptionService()
    versions = await svc.list_versions(asset.id, db)
    active = next((v for v in versions if v.is_active), None)
    assert active is not None
    assert "studio lighting" in active.text


@pytest.mark.asyncio
async def test_bulk_append_returns_400_when_suffix_is_missing(db):
    project = await _create_project(db, "bulk-append-missing")
    asset = await _create_asset(db, project.id)

    async with _client_for_db(db) as client:
        r = await client.post(
            "/api/captions/bulk_append",
            json={"asset_ids": [asset.id], "suffix": ""},
        )

    assert r.status_code == 400


# ── Tests: bulk replace ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_bulk_replace_substitutes_matching_text(db):
    project = await _create_project(db, "bulk-replace")
    asset = await _create_asset(db, project.id)
    await _create_caption(db, asset.id, "portrait of a woman, smiling")

    async with _client_for_db(db) as client:
        r = await client.post(
            "/api/captions/bulk_replace",
            json={
                "asset_ids": [asset.id],
                "find": "woman",
                "replace": "person",
            },
        )

    assert r.status_code == 200
    assert r.json()["updated"] == 1

    svc = CaptionService()
    versions = await svc.list_versions(asset.id, db)
    active = next((v for v in versions if v.is_active), None)
    assert active is not None
    assert "person" in active.text
    assert "woman" not in active.text


@pytest.mark.asyncio
async def test_bulk_replace_skips_assets_with_no_match(db):
    project = await _create_project(db, "bulk-replace-no-match")
    asset = await _create_asset(db, project.id)
    await _create_caption(db, asset.id, "studio portrait, clean background")

    async with _client_for_db(db) as client:
        r = await client.post(
            "/api/captions/bulk_replace",
            json={
                "asset_ids": [asset.id],
                "find": "outdoor",
                "replace": "indoor",
            },
        )

    assert r.status_code == 200
    assert r.json()["updated"] == 0


# ── Tests: consistency check ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_consistency_check_reports_uncaptioned_assets(db):
    project = await _create_project(db, "consistency-check")
    captioned = await _create_asset(db, project.id, "captioned.png")
    uncaptioned = await _create_asset(db, project.id, "uncaptioned.png")
    caption = await _create_caption(db, captioned.id, "a nice portrait of a woman")
    captioned.active_caption_id = caption.id
    await db.flush()

    async with _client_for_db(db) as client:
        r = await client.get(f"/api/projects/{project.id}/captions/consistency")

    assert r.status_code == 200
    body = r.json()
    assert body["total_captioned"] == 1
    assert body["total_uncaptioned"] == 1
    recs = body["recommendations"]
    assert any("missing captions" in rec.lower() or "1 assets" in rec for rec in recs)


@pytest.mark.asyncio
async def test_consistency_check_detects_trigger_word_coverage(db):
    project = await _create_project(db, "trigger-word-check")
    for i in range(4):
        asset = await _create_asset(db, project.id, f"img_{i}.png")
        text = "ohwx person, portrait" if i < 3 else "portrait only"
        caption = await _create_caption(db, asset.id, text)
        asset.active_caption_id = caption.id
    await db.flush()

    async with _client_for_db(db) as client:
        r = await client.get(
            f"/api/projects/{project.id}/captions/consistency",
            params={"trigger_words": "ohwx person"},
        )

    assert r.status_code == 200
    body = r.json()
    assert "ohwx person" in body["trigger_word_presence"]
    assert body["trigger_word_presence"]["ohwx person"] == 3


# ── Tests: CaptionService unit-level ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_caption_service_normalize_fixes_formatting(db):
    project = await _create_project(db, "normalize")
    asset = await _create_asset(db, project.id)
    caption = await _create_caption(db, asset.id, "  portrait,,  smiling  ,  studio  ")

    svc = CaptionService()
    updated = await svc.normalize([asset.id], db)
    assert updated == 1

    versions = await svc.list_versions(asset.id, db)
    active = next((v for v in versions if v.is_active), None)
    assert active is not None
    assert "  " not in active.text
    assert ",," not in active.text
    assert active.text == active.text.strip()


@pytest.mark.asyncio
async def test_caption_service_bulk_find_replace_with_regex(db):
    project = await _create_project(db, "regex-replace")
    asset = await _create_asset(db, project.id)
    await _create_caption(db, asset.id, "photo 001 and photo 002")

    svc = CaptionService()
    count = await svc.bulk_find_replace(
        [asset.id],
        find=r"photo \d+",
        replace="image",
        db=db,
        use_regex=True,
    )
    assert count == 1

    versions = await svc.list_versions(asset.id, db)
    active = next((v for v in versions if v.is_active), None)
    assert active is not None
    assert "photo" not in active.text
    assert "image" in active.text


@pytest.mark.asyncio
async def test_caption_service_delete_raises_for_active_version(db):
    project = await _create_project(db, "delete-active-svc")
    asset = await _create_asset(db, project.id)
    active = await _create_caption(db, asset.id, "active caption", is_active=True)

    svc = CaptionService()
    with pytest.raises(ValueError, match="Cannot delete the active"):
        await svc.delete_version(active.id, db)


@pytest.mark.asyncio
async def test_caption_service_delete_inactive_version_succeeds(db):
    project = await _create_project(db, "delete-inactive-svc")
    asset = await _create_asset(db, project.id)
    inactive = await _create_caption(db, asset.id, "old caption", is_active=False)

    svc = CaptionService()
    await svc.delete_version(inactive.id, db)

    versions = await svc.list_versions(asset.id, db)
    assert all(v.id != inactive.id for v in versions)


@pytest.mark.asyncio
async def test_caption_service_analyze_consistency_empty_project(db):
    project = await _create_project(db, "analyze-empty")

    svc = CaptionService()
    report = await svc.analyze_consistency(project.id, db)

    assert report.total_captioned == 0
    assert report.recommendations == ["No captions found. Generate captions first."]
