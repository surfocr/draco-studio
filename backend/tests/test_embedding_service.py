"""Tests for services/embedding_service.py."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from models.asset import Asset
from models.project import Project
from services.embedding_service import get_embedding_status, index_asset


async def _project(db) -> Project:
    p = Project(name="embed-svc", description="")
    db.add(p)
    await db.flush()
    return p


async def _asset(db, project_id, filename="e.png", analyzed_at=None) -> Asset:
    a = Asset(
        project_id=project_id,
        filename=filename,
        filepath=f"/tmp/fake/{filename}",
        mime_type="image/png",
        width=512, height=512,
        analyzed_at=analyzed_at,
    )
    db.add(a)
    await db.flush()
    return a


@pytest.mark.asyncio
async def test_index_asset_not_found(db):
    result = await index_asset("nonexistent-id", db)
    assert result is False


@pytest.mark.asyncio
async def test_index_asset_no_provider(db):
    project = await _project(db)
    asset = await _asset(db, project.id)
    await db.commit()
    with patch("providers.registry.get_registry") as mock_reg:
        mock_reg.return_value.get.return_value = None
        result = await index_asset(asset.id, db)
    assert result is False


@pytest.mark.asyncio
async def test_index_asset_success(db):
    project = await _project(db)
    asset = await _asset(db, project.id)
    await db.commit()

    mock_provider = MagicMock()
    mock_provider.embed_image = AsyncMock(return_value=MagicMock(vector=[0.1, 0.2]))
    mock_provider.upsert_embedding = AsyncMock()

    with patch("providers.registry.get_registry") as mock_reg:
        mock_reg.return_value.get.return_value = mock_provider
        result = await index_asset(asset.id, db)
    assert result is True
    mock_provider.embed_image.assert_called_once()
    mock_provider.upsert_embedding.assert_called_once()


@pytest.mark.asyncio
async def test_index_asset_handles_provider_error(db):
    project = await _project(db)
    asset = await _asset(db, project.id)
    await db.commit()

    mock_provider = MagicMock()
    mock_provider.embed_image = AsyncMock(side_effect=RuntimeError("embed failed"))

    with patch("providers.registry.get_registry") as mock_reg:
        mock_reg.return_value.get.return_value = mock_provider
        result = await index_asset(asset.id, db)
    assert result is False


@pytest.mark.asyncio
async def test_get_embedding_status_empty_project(db):
    project = await _project(db)
    await db.commit()
    with patch("providers.registry.get_registry") as mock_reg:
        mock_reg.return_value.get.return_value = None
        status = await get_embedding_status(project.id, db)
    assert status["total_assets"] == 0
    assert status["coverage_pct"] == 0.0


@pytest.mark.asyncio
async def test_get_embedding_status_with_assets(db):
    from datetime import datetime, timezone
    project = await _project(db)
    await _asset(db, project.id, "analyzed.png", analyzed_at=datetime.now(timezone.utc))
    await _asset(db, project.id, "pending.png", analyzed_at=None)
    await db.commit()
    with patch("providers.registry.get_registry") as mock_reg:
        mock_reg.return_value.get.return_value = None
        status = await get_embedding_status(project.id, db)
    assert status["total_assets"] == 2
    assert status["analyzed_assets"] == 1
    assert status["pending_analysis"] == 1
    assert status["coverage_pct"] == 50.0
