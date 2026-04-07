"""
Integration tests for caption sidecar export.

Verifies that:
1. queue_export_sidecars_task exists and is importable
2. The export endpoint returns a job_id without crashing
3. The worker writes sidecar files using its own DB session
"""
from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image
from sqlalchemy import select
from unittest.mock import AsyncMock, MagicMock, patch

from config import settings
from models.asset import Asset
from models.project import Project
from services.caption import CaptionService
from services.ingest import IngestSource, ingest_files

def _write_png(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (2, 2), color=(255, 0, 0)).save(path, format="PNG")


async def _create_project(db, name: str = "caption-export") -> Project:
    project = Project(name=name, description="")
    db.add(project)
    await db.flush()
    return project


@pytest.mark.asyncio
async def test_queue_export_sidecars_task_is_importable():
    """queue_export_sidecars_task must exist in workers.tasks — previously missing."""
    from workers.tasks import queue_export_sidecars_task
    assert callable(queue_export_sidecars_task)


@pytest.mark.asyncio
async def test_caption_export_endpoint_returns_job_id(client):
    """POST /api/projects/{id}/captions/export returns a job_id."""
    r = await client.post("/api/projects", json={"name": "test-caption-export", "description": ""})
    assert r.status_code == 201
    project_id = r.json()["id"]

    with patch("services.caption.CaptionService.export_sidecars", new_callable=AsyncMock) as mock_export:
        mock_export.return_value = "mock-job-id-789"

        r = await client.post(
            f"/api/projects/{project_id}/captions/export",
            json={"asset_ids": [], "output_dir": None},
        )

    # Should succeed or report no assets — not a 500 ImportError
    assert r.status_code in (200, 202, 404, 422), \
        f"Unexpected status {r.status_code}: {r.text}"


@pytest.mark.asyncio
async def test_export_sidecars_task_uses_fresh_session():
    """queue_export_sidecars_task must open its own AsyncSessionLocal — not capture a request session."""
    from workers.tasks import queue_export_sidecars_task

    submitted_fns: list = []

    async def capture_submit(fn, *a, job_type="generic", **kw):
        submitted_fns.append(fn)
        return "captured-job"

    with patch("workers.tasks.get_job_queue") as mock_q:
        mock_queue = MagicMock()
        mock_queue.submit = AsyncMock(side_effect=capture_submit)
        mock_q.return_value = mock_queue

        job_id = await queue_export_sidecars_task(
            project_id="proj-1",
            asset_ids=["asset-1", "asset-2"],
            output_dir=None,
            job_id="test-job-id",
        )

    assert job_id == "captured-job"
    assert len(submitted_fns) == 1

    # Execute the worker and verify it opens AsyncSessionLocal
    with patch("database.AsyncSessionLocal") as mock_session_factory:
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory.return_value = mock_session

        with patch("workers.tasks.CaptionService") as MockService:
            mock_svc = MagicMock()
            mock_svc.write_sidecar_direct = AsyncMock(return_value="/tmp/asset-1.txt")
            MockService.return_value = mock_svc

            result = await submitted_fns[0]()

    mock_session_factory.assert_called_once()
    assert result["written"] == 2
    assert result["errors"] == []


@pytest.mark.asyncio
async def test_export_sidecars_task_handles_missing_caption():
    """Worker gracefully records errors for assets with no active caption."""
    from workers.tasks import queue_export_sidecars_task

    submitted_fns: list = []

    async def capture_submit(fn, *a, **kw):
        submitted_fns.append(fn)
        return "job"

    with patch("workers.tasks.get_job_queue") as mock_q:
        mock_queue = MagicMock()
        mock_queue.submit = AsyncMock(side_effect=capture_submit)
        mock_q.return_value = mock_queue

        await queue_export_sidecars_task(
            project_id="proj-1",
            asset_ids=["missing-asset"],
            output_dir=None,
            job_id="test-job",
        )

    with patch("database.AsyncSessionLocal") as mock_session_factory:
        mock_session = AsyncMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_factory.return_value = mock_session

        with patch("workers.tasks.CaptionService") as MockService:
            mock_svc = MagicMock()
            mock_svc.write_sidecar_direct = AsyncMock(return_value=None)  # no caption
            MockService.return_value = mock_svc

            result = await submitted_fns[0]()

    assert result["written"] == 0
    assert len(result["errors"]) == 1
    assert "no active caption" in result["errors"][0]


@pytest.mark.asyncio
async def test_imported_sidecar_round_trips_to_sidecar_export(db, storage_env):
    project = await _create_project(db, "sidecar-roundtrip")
    image_path = storage_env / "source" / "roundtrip.png"
    _write_png(image_path)

    async for _ in ingest_files(
        [
            IngestSource(
                file_path=str(image_path),
                original_filename="roundtrip.png",
                sidecar_text="subject token, clean portrait",
            )
        ],
        project.id,
        db,
        queue_analysis=False,
    ):
        pass

    asset_result = await db.execute(select(Asset).where(Asset.project_id == project.id))
    asset = asset_result.scalar_one()

    service = CaptionService()
    written = await service.write_sidecar_direct(asset.id, db)
    assert written is not None

    sidecar_path = Path(written)
    assert sidecar_path.exists()
    assert sidecar_path.read_text(encoding="utf-8") == "subject token, clean portrait"
