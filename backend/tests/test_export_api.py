from __future__ import annotations

from contextlib import asynccontextmanager
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from database import get_db
from api.export import recover_stale_export_jobs
from models.asset import Asset
from models.caption import CaptionVersion
from models.export import ExportJob
from models.project import Project


async def _create_project(db, name: str = "export") -> Project:
    project = Project(name=name, description="")
    db.add(project)
    await db.flush()
    return project


async def _create_captioned_asset(db, project_id: str) -> Asset:
    asset = Asset(
        project_id=project_id,
        filename="sample.png",
        filepath="C:/dataset/sample.png",
        mime_type="image/png",
        width=512,
        height=512,
        composite_score=0.9,
    )
    db.add(asset)
    await db.flush()

    caption = CaptionVersion(
        asset_id=asset.id,
        text="trigger, portrait",
        style="training_literal",
        provider="test",
        model="test",
        is_active=True,
    )
    db.add(caption)
    await db.flush()

    asset.active_caption_id = caption.id
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
async def test_lora_export_normalizes_image_format(db):
    project = await _create_project(db)
    await _create_captioned_asset(db, project.id)

    with patch("workers.job_queue.get_job_queue") as mock_q:
        mock_queue = MagicMock()
        mock_queue.submit = AsyncMock(return_value="export-job-runner")
        mock_q.return_value = mock_queue

        async with _client_for_db(db) as client:
            response = await client.post(
                f"/api/projects/{project.id}/export/lora",
                json={
                    "trigger_word": "ohwx person",
                    "image_format": "PNG",
                    "dataset_name": "demo",
                },
            )

    assert response.status_code == 202, response.text
    export_job = (await db.execute(select(ExportJob))).scalar_one()
    assert export_job.export_options["image_format"] == "png"
    assert export_job.export_options["_queue_job_id"] == "export-job-runner"


@pytest.mark.asyncio
async def test_lora_export_can_scope_to_selected_asset_ids(db):
    project = await _create_project(db, "export-selected")
    selected_asset = await _create_captioned_asset(db, project.id)
    await _create_captioned_asset(db, project.id)

    with patch("workers.job_queue.get_job_queue") as mock_q:
        mock_queue = MagicMock()
        mock_queue.submit = AsyncMock(return_value="export-job-selected")
        mock_q.return_value = mock_queue

        async with _client_for_db(db) as client:
            response = await client.post(
                f"/api/projects/{project.id}/export/lora",
                json={
                    "trigger_word": "ohwx person",
                    "asset_ids": [selected_asset.id],
                    "dataset_name": "selected-only",
                },
            )

    assert response.status_code == 202, response.text
    assert response.json()["asset_count"] == 1
    export_job = (await db.execute(select(ExportJob).order_by(ExportJob.created_at.desc()))).scalars().first()
    assert export_job is not None
    assert export_job.export_options["asset_ids"] == [selected_asset.id]


@pytest.mark.asyncio
async def test_lora_export_rejects_unsupported_image_format(db):
    project = await _create_project(db, "export-invalid")
    await _create_captioned_asset(db, project.id)

    async with _client_for_db(db) as client:
        response = await client.post(
            f"/api/projects/{project.id}/export/lora",
            json={
                "trigger_word": "ohwx person",
                "image_format": "bmp",
                "dataset_name": "demo",
            },
        )

    assert response.status_code == 422, response.text
    assert "Unsupported image_format" in response.json()["detail"]


@pytest.mark.asyncio
async def test_lora_export_rejects_directory_only_mode(db):
    project = await _create_project(db, "export-nozip")
    await _create_captioned_asset(db, project.id)

    async with _client_for_db(db) as client:
        response = await client.post(
            f"/api/projects/{project.id}/export/lora",
            json={
                "trigger_word": "ohwx person",
                "create_zip": False,
            },
        )

    assert response.status_code == 422, response.text
    assert "Enable ZIP archive creation" in response.json()["detail"]


@pytest.mark.asyncio
async def test_cancel_export_job_marks_export_job_cancelled(db):
    project = await _create_project(db, "export-cancel")
    export_job = ExportJob(
        project_id=project.id,
        export_format="lora",
        status="running",
        export_options={"_queue_job_id": "queue-job-1"},
        total_assets=10,
    )
    db.add(export_job)
    await db.commit()

    with patch("workers.job_queue.get_job_queue") as mock_get_queue:
        mock_queue = MagicMock()
        mock_queue.cancel = AsyncMock(return_value=True)
        mock_get_queue.return_value = mock_queue

        async with _client_for_db(db) as client:
            response = await client.post(f"/api/export/jobs/{export_job.id}/cancel")

    assert response.status_code == 200, response.text
    await db.refresh(export_job)
    assert export_job.status == "cancelled"
    assert export_job.error_message == "Export cancelled by user"


@pytest.mark.asyncio
async def test_recover_stale_export_jobs_marks_running_jobs_failed(db):
    project = await _create_project(db, "export-recover")
    running_job = ExportJob(project_id=project.id, export_format="zip", status="running")
    pending_job = ExportJob(project_id=project.id, export_format="lora", status="pending")
    done_job = ExportJob(project_id=project.id, export_format="kohya", status="done")
    db.add_all([running_job, pending_job, done_job])
    await db.commit()

    recovered = await recover_stale_export_jobs(db)

    assert recovered == 2
    await db.refresh(running_job)
    await db.refresh(pending_job)
    await db.refresh(done_job)
    assert running_job.status == "failed"
    assert pending_job.status == "failed"
    assert done_job.status == "done"
    assert running_job.error_message == "Export interrupted by application restart"


@pytest.mark.asyncio
async def test_download_export_rejects_paths_outside_managed_locations(db):
    project = await _create_project(db, "export-unsafe-download")
    export_job = ExportJob(
        project_id=project.id,
        export_format="zip",
        status="done",
        output_path=__file__,
    )
    db.add(export_job)
    await db.commit()

    async with _client_for_db(db) as client:
        response = await client.get(f"/api/export/jobs/{export_job.id}/download")

    assert response.status_code == 403, response.text
    assert "outside Draco-managed export locations" in response.json()["detail"]


@pytest.mark.asyncio
async def test_download_export_requires_archive_file(db):
    project = await _create_project(db, "export-dir-download")
    export_dir = tempfile.mkdtemp(prefix="draco_export_test_")
    export_job = ExportJob(
        project_id=project.id,
        export_format="lora",
        status="done",
        output_path=export_dir,
    )
    db.add(export_job)
    await db.commit()

    async with _client_for_db(db) as client:
        response = await client.get(f"/api/export/jobs/{export_job.id}/download")

    assert response.status_code == 409, response.text
    assert "downloadable archive" in response.json()["detail"]


@pytest.mark.asyncio
async def test_preview_export_supports_lora_filter_shape(db):
    project = await _create_project(db, "export-preview")
    approved = await _create_captioned_asset(db, project.id)
    unapproved = await _create_captioned_asset(db, project.id)
    approved.review_state = "approved"
    approved.composite_score = 0.95
    unapproved.composite_score = 0.2
    await db.commit()

    async with _client_for_db(db) as client:
        response = await client.post(
            f"/api/projects/{project.id}/export/preview",
            json={
                "include_only_captioned": True,
                "include_only_approved": True,
                "min_score": 0.5,
                "max_images": 10,
            },
        )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "count": 1,
        "captioned_count": 1,
        "uncaptioned_count": 0,
    }
