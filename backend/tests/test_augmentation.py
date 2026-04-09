from __future__ import annotations

from pathlib import Path

import pytest
from unittest.mock import AsyncMock, patch

from models.asset import Asset
from models.augmentation import AugmentationJob
from models.project import Project
from services.augmentation import AugmentationService


async def _create_project(db, name: str = "augmentation") -> Project:
    project = Project(name=name, description="")
    db.add(project)
    await db.flush()
    return project


async def _create_asset(db, project_id: str, filename: str, *, rejected: bool = False) -> Asset:
    asset = Asset(
        project_id=project_id,
        filename=filename,
        filepath=f"C:/dataset/{filename}",
        mime_type="image/png",
        width=1024,
        height=1024,
        sha256_hash=filename,
        composite_score=0.75,
        is_rejected=rejected,
        review_state="rejected" if rejected else "pending",
    )
    db.add(asset)
    await db.flush()
    return asset


@pytest.mark.asyncio
async def test_resolve_auto_fit_asset_ids_uses_all_non_rejected_assets_when_selection_empty(db):
    project = await _create_project(db, "auto-fit-all")
    keep_a = await _create_asset(db, project.id, "keep-a.png")
    keep_b = await _create_asset(db, project.id, "keep-b.png")
    _rejected = await _create_asset(db, project.id, "rejected.png", rejected=True)
    await db.commit()

    service = AugmentationService()
    resolved = await service._resolve_auto_fit_asset_ids(
        project_id=project.id,
        asset_ids=[],
        db=db,
    )

    assert set(resolved) == {keep_a.id, keep_b.id}


@pytest.mark.asyncio
async def test_list_pending_results_filters_by_project(db):
    project_a = await _create_project(db, "proj-a")
    project_b = await _create_project(db, "proj-b")
    asset_a = await _create_asset(db, project_a.id, "a.png")
    asset_b = await _create_asset(db, project_b.id, "b.png")
    db.add(
        AugmentationJob(
            project_id=project_a.id,
            source_asset_id=asset_a.id,
            augmentation_type="outpaint",
            provider="basic_editor",
            status="pending_review",
        )
    )
    db.add(
        AugmentationJob(
            project_id=project_b.id,
            source_asset_id=asset_b.id,
            augmentation_type="outpaint",
            provider="basic_editor",
            status="pending_review",
        )
    )
    await db.commit()

    service = AugmentationService()
    only_a = await service.list_pending_results(db, project_id=project_a.id)

    assert len(only_a) == 1
    assert only_a[0].project_id == project_a.id


@pytest.mark.asyncio
async def test_augmentation_preview_endpoint_serves_result_file(client, db, tmp_path):
    from config import settings
    project = await _create_project(db, "preview")
    asset = await _create_asset(db, project.id, "source.png")
    # Write output inside STORAGE_PATH so path traversal check passes
    storage = Path(settings.STORAGE_PATH)
    storage.mkdir(parents=True, exist_ok=True)
    output = storage / "test_preview.png"
    output.write_bytes(b"fake-image")
    try:
        job = AugmentationJob(
            project_id=project.id,
            source_asset_id=asset.id,
            augmentation_type="outpaint",
            provider="basic_editor",
            status="pending_review",
            output_path=str(output),
        )
        db.add(job)
        await db.commit()

        response = await client.get(f"/api/augmentation/preview/{job.id}")

        assert response.status_code == 200
        assert response.content == b"fake-image"
    finally:
        output.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_augmentation_preview_endpoint_404s_for_missing_file(client, db):
    from config import settings
    project = await _create_project(db, "missing-preview")
    asset = await _create_asset(db, project.id, "source.png")
    # Use a path inside STORAGE_PATH that doesn't exist on disk
    missing = Path(settings.STORAGE_PATH) / "definitely_missing_file.png"
    job = AugmentationJob(
        project_id=project.id,
        source_asset_id=asset.id,
        augmentation_type="outpaint",
        provider="basic_editor",
        status="pending_review",
        output_path=str(missing),
    )
    db.add(job)
    await db.commit()

    response = await client.get(f"/api/augmentation/preview/{job.id}")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_auto_fit_endpoint_uses_all_assets_when_selection_empty(client, db):
    project = await _create_project(db, "auto-fit-route")
    await _create_asset(db, project.id, "one.png")
    await _create_asset(db, project.id, "two.png")
    await db.commit()

    with patch("api.augmentation._service.auto_fit_assets", new_callable=AsyncMock) as mock_auto_fit:
        mock_auto_fit.return_value = "augmentation-job-1"
        response = await client.post(
            f"/api/projects/{project.id}/augmentation/auto-fit",
            json={
                "asset_ids": [],
                "target_width": 1024,
                "target_height": 1024,
                "provider": "auto",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json() == {"job_id": "augmentation-job-1", "asset_count": 2}
    mock_auto_fit.assert_awaited_once()


@pytest.mark.asyncio
async def test_auto_fit_endpoint_rejects_empty_project(client):
    create = await client.post("/api/projects", json={"name": "empty-augmentation"})
    project_id = create.json()["id"]

    response = await client.post(
        f"/api/projects/{project_id}/augmentation/auto-fit",
        json={
            "asset_ids": [],
            "target_width": 1024,
            "target_height": 1024,
            "provider": "auto",
        },
    )

    assert response.status_code == 400
    assert "No eligible assets" in response.text
