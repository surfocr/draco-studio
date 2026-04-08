"""Tests for the Captions API endpoints."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from models.asset import Asset
from models.caption import CaptionVersion
from models.project import Project


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _setup(db):
    project = Project(name="caption-test", description="")
    db.add(project)
    await db.flush()
    asset = Asset(
        project_id=project.id,
        filename="photo.png",
        filepath="/tmp/dataset/photo.png",
        mime_type="image/png",
        width=512,
        height=512,
    )
    db.add(asset)
    await db.flush()
    return project, asset


async def _add_caption(
    db,
    asset_id,
    text="A test caption",
    style="natural",
    provider="test",
    is_active=False,
):
    cv = CaptionVersion(
        asset_id=asset_id,
        text=text,
        style=style,
        provider=provider,
        is_active=is_active,
    )
    db.add(cv)
    await db.flush()
    return cv


# ── GET /api/assets/{asset_id}/captions (list_captions) ──────────────────────


@pytest.mark.asyncio
async def test_list_captions_empty(client, db):
    """Asset with no captions returns an empty list."""
    _, asset = await _setup(db)
    await db.commit()

    r = await client.get(f"/api/assets/{asset.id}/captions")
    assert r.status_code == 200
    assert r.json() == []


@pytest.mark.asyncio
async def test_list_captions_multiple(client, db):
    """Asset with multiple captions returns them all."""
    _, asset = await _setup(db)
    c1 = await _add_caption(db, asset.id, text="First caption")
    c2 = await _add_caption(db, asset.id, text="Second caption")
    await db.commit()

    r = await client.get(f"/api/assets/{asset.id}/captions")
    assert r.status_code == 200
    body = r.json()
    assert len(body) == 2
    returned_ids = {item["id"] for item in body}
    assert {c1.id, c2.id} == returned_ids


# ── PUT /api/captions/{version_id}/activate ──────────────────────────────────


@pytest.mark.asyncio
async def test_activate_caption(client, db):
    """Activating a caption version returns ok and identifiers."""
    _, asset = await _setup(db)
    cv = await _add_caption(db, asset.id, text="Activate me")
    await db.commit()

    r = await client.put(f"/api/captions/{cv.id}/activate")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["version_id"] == cv.id
    assert body["asset_id"] == asset.id


@pytest.mark.asyncio
async def test_activate_caption_not_found(client):
    """Activating a nonexistent version returns 404."""
    r = await client.put("/api/captions/nonexistent-version-id/activate")
    assert r.status_code == 404


# ── DELETE /api/captions/{version_id} ────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_caption(client, db):
    """Deleting an inactive caption returns 204."""
    _, asset = await _setup(db)
    cv = await _add_caption(db, asset.id, text="Delete me", is_active=False)
    await db.commit()

    r = await client.delete(f"/api/captions/{cv.id}")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_delete_caption_not_found(client):
    """Deleting a nonexistent version returns 404."""
    r = await client.delete("/api/captions/nonexistent-version-id")
    assert r.status_code == 404


# ── POST /api/captions/bulk_prepend (legacy) ─────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_prepend(client, db):
    """Prepending text to captions returns updated count."""
    _, asset = await _setup(db)
    await _add_caption(db, asset.id, text="original", is_active=True)
    await db.commit()

    mock_svc = AsyncMock()
    mock_svc.bulk_prepend.return_value = 1

    with patch("api.captions.get_caption_service", return_value=mock_svc):
        r = await client.post(
            "/api/captions/bulk_prepend",
            json={"asset_ids": [asset.id], "prefix": "PREFIX"},
        )

    assert r.status_code == 200
    assert r.json()["updated"] == 1
    mock_svc.bulk_prepend.assert_awaited_once()


@pytest.mark.asyncio
async def test_bulk_prepend_missing_prefix(client):
    """Missing prefix returns 400."""
    r = await client.post(
        "/api/captions/bulk_prepend",
        json={"asset_ids": ["some-id"]},
    )
    assert r.status_code == 400


# ── POST /api/captions/bulk_append (legacy) ──────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_append(client, db):
    """Appending text to captions returns updated count."""
    _, asset = await _setup(db)
    await _add_caption(db, asset.id, text="original", is_active=True)
    await db.commit()

    mock_svc = AsyncMock()
    mock_svc.bulk_append.return_value = 1

    with patch("api.captions.get_caption_service", return_value=mock_svc):
        r = await client.post(
            "/api/captions/bulk_append",
            json={"asset_ids": [asset.id], "suffix": "SUFFIX"},
        )

    assert r.status_code == 200
    assert r.json()["updated"] == 1
    mock_svc.bulk_append.assert_awaited_once()


@pytest.mark.asyncio
async def test_bulk_append_missing_suffix(client):
    """Missing suffix returns 400."""
    r = await client.post(
        "/api/captions/bulk_append",
        json={"asset_ids": ["some-id"]},
    )
    assert r.status_code == 400


# ── POST /api/captions/bulk_replace (legacy) ─────────────────────────────────


@pytest.mark.asyncio
async def test_bulk_replace(client, db):
    """Find-and-replace in captions returns updated count."""
    _, asset = await _setup(db)
    await _add_caption(db, asset.id, text="hello world", is_active=True)
    await db.commit()

    mock_svc = AsyncMock()
    mock_svc.bulk_find_replace.return_value = 1

    with patch("api.captions.get_caption_service", return_value=mock_svc):
        r = await client.post(
            "/api/captions/bulk_replace",
            json={
                "asset_ids": [asset.id],
                "find": "hello",
                "replace": "goodbye",
            },
        )

    assert r.status_code == 200
    assert r.json()["updated"] == 1
    mock_svc.bulk_find_replace.assert_awaited_once()
