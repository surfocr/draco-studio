"""Ingest tests focused on provenance, sidecars, and worker boundaries."""
from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image
from sqlalchemy import select

from config import settings
from models.asset import Asset
from models.caption import CaptionVersion
from models.project import Project
from providers.registry import get_registry
from services.ingest import IngestSource, ingest_directory, ingest_files

def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), color=(255, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def storage_env(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_PATH", str(tmp_path / "storage"))
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path / "data"))
    settings.storage_path.mkdir(parents=True, exist_ok=True)
    settings.data_dir.mkdir(parents=True, exist_ok=True)

    registry = get_registry()
    registry._instances.clear()
    # Register default providers so tests that call ingest_files directly
    # (without the full app lifespan) have a working storage provider.
    from providers.registry import register_default_providers
    register_default_providers(registry)
    yield tmp_path
    registry._instances.clear()


async def _create_project(db, name: str = "ingest-project") -> Project:
    project = Project(name=name, description="")
    db.add(project)
    await db.flush()
    return project


def _write_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (2, 2), color=(255, 0, 0)).save(path, format="PNG")


@pytest.mark.asyncio
async def test_ingest_upload_returns_job_id(client):
    r = await client.post("/api/projects", json={"name": "test-ingest", "description": ""})
    assert r.status_code == 201, r.text
    project_id = r.json()["id"]

    with patch("workers.job_queue.get_job_queue") as mock_q:
        mock_queue = MagicMock()
        mock_queue.submit = AsyncMock(return_value="test-job-123")
        mock_q.return_value = mock_queue

        r = await client.post(
            f"/api/projects/{project_id}/assets/ingest",
            files={"files": ("test.png", io.BytesIO(_png_bytes()), "image/png")},
            data={"queue_analysis": "false"},
        )

    assert r.status_code == 202, r.text
    body = r.json()
    assert body["job_id"] == "test-job-123"
    assert body["file_count"] == 1


@pytest.mark.asyncio
async def test_ingest_dir_returns_job_id(client, storage_env):
    r = await client.post("/api/projects", json={"name": "test-ingest-dir", "description": ""})
    assert r.status_code == 201
    project_id = r.json()["id"]

    ingest_dir_path = settings.data_dir / "ingest-dir-test"
    ingest_dir_path.mkdir(parents=True, exist_ok=True)

    with patch("workers.job_queue.get_job_queue") as mock_q:
        mock_queue = MagicMock()
        mock_queue.submit = AsyncMock(return_value="test-job-456")
        mock_q.return_value = mock_queue

        r = await client.post(
            f"/api/projects/{project_id}/assets/ingest-directory",
            json={"directory_path": str(ingest_dir_path), "recursive": False, "queue_analysis": False},
        )

    assert r.status_code == 202, r.text
    body = r.json()
    assert body["job_id"] == "test-job-456"
    assert body["directory"] == str(ingest_dir_path)


@pytest.mark.asyncio
async def test_ingest_worker_uses_fresh_session():
    import inspect

    import backend.api.assets as assets_module

    source = inspect.getsource(assets_module)
    assert "AsyncSessionLocal" in source
    assert "_run_ingest" in source
    assert "_run" in source


@pytest.mark.asyncio
async def test_ingest_files_preserves_original_filename_and_imports_sidecar(db, storage_env):
    project = await _create_project(db)
    image_path = storage_env / "source" / "portrait.png"
    _write_png(image_path)

    async for _ in ingest_files(
        [
            IngestSource(
                file_path=str(image_path),
                original_filename="portrait.png",
                sidecar_text="trigger, smiling portrait",
            )
        ],
        project.id,
        db,
        queue_analysis=False,
    ):
        pass

    asset_result = await db.execute(select(Asset).where(Asset.project_id == project.id))
    asset = asset_result.scalar_one()
    assert asset.filename == "portrait.png"
    assert asset.active_caption_id is not None
    assert asset.caption_provider == "sidecar_import"

    caption = await db.get(CaptionVersion, asset.active_caption_id)
    assert caption is not None
    assert caption.text == "trigger, smiling portrait"
    assert caption.style == "training_literal"
    assert caption.is_active is True


@pytest.mark.asyncio
async def test_ingest_directory_imports_matching_txt_sidecar(db, storage_env):
    project = await _create_project(db, "dir-sidecar")
    ingest_root = settings.data_dir / "folder_ingest"
    ingest_root.mkdir(parents=True, exist_ok=True)
    image_path = ingest_root / "subject.png"
    _write_png(image_path)
    image_path.with_suffix(".txt").write_text("subject token, studio portrait", encoding="utf-8")

    async for _ in ingest_directory(str(ingest_root), project.id, db, recursive=False, queue_analysis=False):
        pass

    asset_result = await db.execute(select(Asset).where(Asset.project_id == project.id))
    asset = asset_result.scalar_one()
    caption = await db.get(CaptionVersion, asset.active_caption_id)
    assert caption is not None
    assert caption.text == "subject token, studio portrait"


@pytest.mark.asyncio
async def test_ingest_skips_corrupt_images_without_creating_asset(db, storage_env):
    project = await _create_project(db, "corrupt-ingest")
    bad_path = storage_env / "source" / "broken.png"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_bytes(b"not-a-real-png")

    progresses = [
        progress
        async for progress in ingest_files(
            [IngestSource(file_path=str(bad_path), original_filename="broken.png")],
            project.id,
            db,
            queue_analysis=False,
        )
    ]

    assert progresses[-1].errors
    asset_result = await db.execute(select(Asset).where(Asset.project_id == project.id))
    assert asset_result.scalars().all() == []


@pytest.mark.asyncio
async def test_ingest_generates_single_thumbnail_pair(db, storage_env):
    project = await _create_project(db, "thumbnail-ingest")
    image_path = storage_env / "source" / "thumb.png"
    _write_png(image_path)

    async for _ in ingest_files(
        [IngestSource(file_path=str(image_path), original_filename="thumb.png")],
        project.id,
        db,
        queue_analysis=False,
    ):
        pass

    asset_result = await db.execute(select(Asset).where(Asset.project_id == project.id))
    asset = asset_result.scalar_one()
    assert asset.thumbnail_path
    assert asset.thumbnail_small_path

    thumb_dir = settings.storage_path / project.id / "thumbnails"
    files = sorted(p.name for p in thumb_dir.iterdir() if p.is_file())
    assert files == [
        f"{asset.id}_{settings.THUMBNAIL_SIZE}.webp",
        f"{asset.id}_sm_{settings.THUMBNAIL_SMALL_SIZE}.webp",
    ]
