from __future__ import annotations

import io
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from PIL import Image
from sqlalchemy import select

from config import settings
from database import get_db
from models.asset import Asset, ReviewState
from models.project import Project
from providers.base import ProviderBase
from providers.registry import get_registry
from providers.storage.local import LocalStorageProvider
from services.asset_state import AssetStateService


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (8, 8), color=(255, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


class MockEmbeddingProvider(ProviderBase):
    provider_id = "mock_embedding"
    deleted_ids: list[str] = []

    async def is_available(self) -> bool:
        return True

    async def health_check(self) -> dict:
        return {"ok": True, "latency_ms": 0.0, "details": {}}

    async def delete_embedding(self, asset_id: str) -> None:
        self.deleted_ids.append(asset_id)


@pytest.fixture
def storage_env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path / "data"))
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    registry = get_registry()
    registry._classes.clear()
    registry._instances.clear()
    registry._configs.clear()
    registry.register("storage", "local", LocalStorageProvider)
    registry.register("embedding", "fastembed", MockEmbeddingProvider)
    MockEmbeddingProvider.deleted_ids = []
    yield tmp_path
    registry._classes.clear()
    registry._instances.clear()
    registry._configs.clear()


async def _create_project(db, name: str = "asset-state") -> Project:
    project = Project(name=name, description="")
    db.add(project)
    await db.flush()
    return project


def _write_project_file(project_id: str, filename: str) -> str:
    assets_dir = settings.storage_path / project_id / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    path = assets_dir / filename
    path.write_bytes(_png_bytes())
    return str(path)


async def _create_asset(
    db,
    project_id: str,
    filename: str,
    *,
    review_state: str = ReviewState.PENDING.value,
    is_flagged: bool = False,
    is_rejected: bool = False,
) -> Asset:
    asset = Asset(
        project_id=project_id,
        filename=filename,
        filepath=_write_project_file(project_id, filename),
        mime_type="image/png",
        file_size=len(_png_bytes()),
        width=8,
        height=8,
        review_state=review_state,
        is_flagged=is_flagged,
        is_rejected=is_rejected,
    )
    db.add(asset)
    await db.flush()
    return asset


@asynccontextmanager
async def _client_for_db(db):
    from main import app

    async def override_get_db():
        yield db

    app.dependency_overrides[get_db] = override_get_db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_asset_state_service_updates_review_and_flag_counters(db, storage_env):
    project = await _create_project(db)
    asset_a = await _create_asset(db, project.id, "a.png")
    asset_b = await _create_asset(db, project.id, "b.png")

    await AssetStateService.approve_asset(asset_a, db)
    await AssetStateService.reject_asset(asset_b, db, rejection_reason="bad crop")
    await AssetStateService.flag_asset(asset_a, db)
    counts = await AssetStateService.sync_project_counters(project.id, db)

    assert counts == {
        "asset_count": 2,
        "reviewed_count": 2,
        "flagged_count": 1,
        "rejected_count": 1,
    }
    assert asset_a.review_state == ReviewState.APPROVED.value
    assert asset_a.is_rejected is False
    assert asset_a.is_flagged is True
    assert asset_b.review_state == ReviewState.REJECTED.value
    assert asset_b.is_rejected is True
    assert asset_b.rejection_reason == "bad crop"

    await AssetStateService.unflag_asset(asset_a, db)
    counts = await AssetStateService.sync_project_counters(project.id, db)
    assert counts["flagged_count"] == 0


@pytest.mark.asyncio
async def test_delete_asset_moves_file_to_trash_and_cleans_embedding(db, storage_env):
    project = await _create_project(db, "delete-check")
    asset = await _create_asset(db, project.id, "delete-me.png")
    await AssetStateService.sync_project_counters(project.id, db)

    original_path = Path(asset.filepath)
    assert original_path.exists()

    await AssetStateService.delete_asset(asset, db)
    counts = await AssetStateService.sync_project_counters(project.id, db)

    deleted_asset = await db.get(Asset, asset.id)
    trash_path = settings.storage_path / project.id / ".trash" / "delete-me.png"

    assert deleted_asset is None
    assert original_path.exists() is False
    assert trash_path.exists()
    assert counts["asset_count"] == 0
    assert MockEmbeddingProvider.deleted_ids == [asset.id]


@pytest.mark.asyncio
async def test_bulk_action_uses_shared_state_semantics(db, storage_env):
    project = await _create_project(db, "bulk-action")
    asset_a = await _create_asset(db, project.id, "approve.png")
    asset_b = await _create_asset(db, project.id, "reject.png")

    async with _client_for_db(db) as client:
        response = await client.post(
            f"/api/projects/{project.id}/assets/bulk-action",
            data={
                "action": "reject",
                "asset_ids": [asset_a.id, asset_b.id],
            },
        )

    assert response.status_code == 200, response.text
    await db.refresh(project)
    refreshed_a = await db.get(Asset, asset_a.id)
    refreshed_b = await db.get(Asset, asset_b.id)

    assert project.reviewed_count == 2
    assert project.rejected_count == 2
    assert refreshed_a.review_state == ReviewState.REJECTED.value
    assert refreshed_b.review_state == ReviewState.REJECTED.value


@pytest.mark.asyncio
async def test_admin_recount_repairs_drifted_project_counts(db, storage_env):
    project = await _create_project(db, "recount")
    await _create_asset(db, project.id, "pending.png")
    approved = await _create_asset(db, project.id, "approved.png")
    rejected = await _create_asset(db, project.id, "rejected.png", is_rejected=True)

    await AssetStateService.approve_asset(approved, db)
    await AssetStateService.reject_asset(rejected, db)

    project.asset_count = 999
    project.reviewed_count = 999
    project.flagged_count = 999
    project.rejected_count = 999
    await db.flush()

    async with _client_for_db(db) as client:
        response = await client.post(f"/api/admin/projects/{project.id}/recount")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["asset_count"] == 3
    assert body["reviewed_count"] == 2
    assert body["flagged_count"] == 0
    assert body["rejected_count"] == 1

    await db.refresh(project)
    assert project.asset_count == 3
    assert project.reviewed_count == 2


@pytest.mark.asyncio
async def test_bulk_delete_moves_files_to_trash_and_recounts(db, storage_env):
    project = await _create_project(db, "bulk-delete")
    asset_a = await _create_asset(db, project.id, "a.png", is_flagged=True)
    asset_b = await _create_asset(db, project.id, "b.png", is_rejected=True)
    await AssetStateService.sync_project_counters(project.id, db)

    async with _client_for_db(db) as client:
        response = await client.post(
            "/api/assets/bulk-delete",
            json={"ids": [asset_a.id, asset_b.id]},
        )

    assert response.status_code == 200, response.text
    assert response.json()["deleted"] == 2
    await db.refresh(project)

    remaining = (await db.execute(select(Asset).where(Asset.project_id == project.id))).scalars().all()
    assert remaining == []
    assert project.asset_count == 0
    assert project.flagged_count == 0
    assert project.rejected_count == 0
    assert (settings.storage_path / project.id / ".trash" / "a.png").exists()
    assert (settings.storage_path / project.id / ".trash" / "b.png").exists()
