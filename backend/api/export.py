"""Export jobs router — full rebuild."""
from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.asset import Asset, ReviewState
from models.export import ExportJob

router = APIRouter(tags=["export"])


# ── Request models ─────────────────────────────────────────────────────────────

class LoRAExportRequest(BaseModel):
    trigger_word: str
    repeats: int = 10
    caption_style: str = "active"
    include_only_captioned: bool = True
    include_only_approved: bool = False
    min_score: float | None = None
    max_images: int | None = None
    image_format: str = "png"
    create_zip: bool = True
    dataset_name: str = "dataset"


class KohyaExportRequest(BaseModel):
    trigger_word: str
    repeats: int = 10
    dataset_name: str = "dataset"
    model_type: str = "sdxl"
    learning_rate: float = 1e-4
    epochs: int = 10
    batch_size: int = 1
    network_rank: int = 32
    network_alpha: int = 16
    caption_style: str = "active"
    generate_train_script: bool = True
    create_zip: bool = True


class ZipExportRequest(BaseModel):
    dataset_name: str = "dataset"
    include_metadata: bool = True
    asset_ids: list[str] | None = None


# ── Helpers ────────────────────────────────────────────────────────────────────

async def _load_eligible_assets(
    project_id: str,
    db: AsyncSession,
    asset_ids: list[str] | None = None,
    include_only_captioned: bool = False,
    include_only_approved: bool = False,
    min_score: float | None = None,
) -> list[Asset]:
    conditions = [
        Asset.project_id == project_id,
        Asset.is_rejected.is_(False),
    ]
    if asset_ids:
        conditions.append(Asset.id.in_(asset_ids))
    if include_only_approved:
        conditions.append(Asset.review_state == ReviewState.APPROVED.value)
    if include_only_captioned:
        conditions.append(Asset.active_caption_id.isnot(None))
    if min_score is not None:
        conditions.append(Asset.composite_score >= min_score)

    result = await db.execute(select(Asset).where(*conditions))
    return result.scalars().all()


async def _load_captions_for_assets(
    asset_ids: list[str],
    db: AsyncSession,
) -> dict[str, str]:
    from models.caption import CaptionVersion

    result = await db.execute(
        select(CaptionVersion).where(
            CaptionVersion.asset_id.in_(asset_ids),
            CaptionVersion.is_active == True,
        )
    )
    return {cv.asset_id: cv.text for cv in result.scalars().all()}


def _build_assets_data(assets: list[Asset], captions: dict[str, str]) -> list[dict]:
    return [
        {
            "id": a.id,
            "filepath": a.filepath,
            "filename": a.filename,
            "caption": captions.get(a.id, ""),
            "composite_score": a.composite_score,
        }
        for a in assets
    ]


async def _create_and_queue_export(
    project_id: str,
    export_format: str,
    assets: list[Asset],
    options: dict,
    db: AsyncSession,
    captions: dict[str, str],
) -> dict:
    """Create ExportJob, queue async task, return response dict."""
    export_job = ExportJob(
        id=str(uuid.uuid4()),
        project_id=project_id,
        export_format=export_format,
        export_options=options,
        total_assets=len(assets),
        status="pending",
    )
    db.add(export_job)
    await db.flush()

    output_dir = tempfile.mkdtemp(prefix=f"draco_export_{export_job.id[:8]}_")
    export_job_id = export_job.id
    assets_data = _build_assets_data(assets, captions)

    async def _run_export() -> None:
        from database import AsyncSessionLocal
        from providers.registry import get_registry

        registry = get_registry()
        exporter_map = {
            "lora": ("export", "lora_exporter"),
            "kohya": ("export", "kohya_exporter"),
            "zip": ("export", "zip_exporter"),
        }

        opts_with_data = {**options, "assets_data": assets_data}
        ptype, pname = exporter_map.get(export_format, ("export", export_format))
        exporter = registry.get(ptype, pname)

        # Lazily create exporter if not in registry
        if not exporter:
            if export_format == "lora":
                from providers.export.lora_exporter import LoRAExporter
                exporter = LoRAExporter()
            elif export_format == "kohya":
                from providers.export.kohya_exporter import KohyaExporter
                exporter = KohyaExporter()
            elif export_format == "zip":
                from providers.export.zip_exporter import ZipExporter
                exporter = ZipExporter()

        async with AsyncSessionLocal() as worker_db:
            job = await worker_db.get(ExportJob, export_job_id)
            if job is None:
                return

            if not exporter:
                job.status = "failed"
                job.error_message = f"No exporter found for format: {export_format}"
                await worker_db.commit()
                return

            try:
                manifest = await exporter.export(
                    [a["id"] for a in assets_data], output_dir, opts_with_data
                )
                job.status = "done"
                job.exported_assets = manifest.asset_count
                job.finished_at = datetime.now(timezone.utc)
                job.output_path = manifest.output_path
            except Exception as e:
                job.status = "failed"
                job.error_message = str(e)
            finally:
                await worker_db.commit()

    from workers.job_queue import get_job_queue

    queue = get_job_queue()
    job_id = await queue.submit(_run_export, job_type=f"export_{export_format}")
    export_job.status = "running"
    await db.commit()

    return {
        "export_job_id": export_job_id,
        "job_id": job_id,
        "asset_count": len(assets),
    }


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post(
    "/api/projects/{project_id}/export/lora",
    status_code=status.HTTP_202_ACCEPTED,
)
async def export_lora(
    project_id: str,
    body: LoRAExportRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    from models.project import Project
    from providers.export.base_exporter import sanitize_filename

    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    assets = await _load_eligible_assets(
        project_id,
        db,
        include_only_captioned=body.include_only_captioned,
        include_only_approved=body.include_only_approved,
        min_score=body.min_score,
    )
    if not assets:
        raise HTTPException(status_code=422, detail="No eligible assets to export")

    if body.max_images is not None and len(assets) > body.max_images:
        assets = sorted(assets, key=lambda a: a.composite_score or 0.0, reverse=True)[: body.max_images]

    captions = await _load_captions_for_assets([a.id for a in assets], db)

    options = {
        "trigger_word": sanitize_filename(body.trigger_word),
        "repeats": body.repeats,
        "caption_style": body.caption_style,
        "include_only_captioned": body.include_only_captioned,
        "include_only_approved": body.include_only_approved,
        "min_score": body.min_score,
        "max_images": body.max_images,
        "image_format": body.image_format,
        "create_zip": body.create_zip,
        "dataset_name": sanitize_filename(body.dataset_name),
    }

    return await _create_and_queue_export(project_id, "lora", assets, options, db, captions)


@router.post(
    "/api/projects/{project_id}/export/kohya",
    status_code=status.HTTP_202_ACCEPTED,
)
async def export_kohya(
    project_id: str,
    body: KohyaExportRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    from models.project import Project
    from providers.export.base_exporter import sanitize_filename

    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    assets = await _load_eligible_assets(
        project_id,
        db,
        include_only_captioned=body.include_only_captioned,
    )
    if not assets:
        raise HTTPException(status_code=422, detail="No eligible assets to export")

    captions = await _load_captions_for_assets([a.id for a in assets], db)

    options = {
        "trigger_word": sanitize_filename(body.trigger_word),
        "repeats": body.repeats,
        "dataset_name": sanitize_filename(body.dataset_name),
        "model_type": body.model_type,
        "learning_rate": body.learning_rate,
        "epochs": body.epochs,
        "batch_size": body.batch_size,
        "network_rank": body.network_rank,
        "network_alpha": body.network_alpha,
        "caption_style": body.caption_style,
        "include_only_captioned": body.include_only_captioned,
        "generate_train_script": body.generate_train_script,
        "create_zip": body.create_zip,
    }

    return await _create_and_queue_export(project_id, "kohya", assets, options, db, captions)


@router.post(
    "/api/projects/{project_id}/export/zip",
    status_code=status.HTTP_202_ACCEPTED,
)
async def export_zip(
    project_id: str,
    body: ZipExportRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    from models.project import Project

    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    assets = await _load_eligible_assets(
        project_id,
        db,
        asset_ids=body.asset_ids,
    )
    if not assets:
        raise HTTPException(status_code=422, detail="No eligible assets to export")

    captions = await _load_captions_for_assets([a.id for a in assets], db)

    options = {
        "dataset_name": body.dataset_name,
        "include_metadata": body.include_metadata,
    }

    return await _create_and_queue_export(project_id, "zip", assets, options, db, captions)


@router.get("/api/export/jobs/{export_job_id}")
async def get_export_job(
    export_job_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    job = await db.get(ExportJob, export_job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")
    return {
        "id": job.id,
        "project_id": job.project_id,
        "export_format": job.export_format,
        "status": job.status,
        "progress": job.progress,
        "exported_assets": job.exported_assets,
        "total_assets": job.total_assets,
        "output_path": job.output_path,
        "error": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


@router.get("/api/export/jobs/{export_job_id}/download")
async def download_export(
    export_job_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileResponse:
    job = await db.get(ExportJob, export_job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Export job not found")
    if job.status != "done":
        raise HTTPException(
            status_code=400,
            detail=f"Export job is not complete (status: {job.status})",
        )
    if not job.output_path:
        raise HTTPException(status_code=404, detail="No output file available")

    output = Path(job.output_path)
    if not output.exists():
        raise HTTPException(status_code=404, detail="Output file not found on disk")

    media_type = "application/zip" if output.suffix == ".zip" else "application/octet-stream"
    return FileResponse(
        path=str(output),
        media_type=media_type,
        filename=output.name,
    )


@router.post("/api/projects/{project_id}/export/preview")
async def preview_export(
    project_id: str,
    body: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Return count of assets that would be exported with given filters."""
    filter_mode = body.get("filter", "approved")
    min_score = body.get("min_score", 0.0)
    include_augmented = body.get("include_augmented", True)

    conditions = [
        Asset.project_id == project_id,
        Asset.is_rejected.is_(False),
    ]

    if filter_mode == "approved":
        conditions.append(Asset.review_state == ReviewState.APPROVED.value)
    elif filter_mode == "scored":
        conditions.append(Asset.composite_score >= min_score)

    if not include_augmented:
        conditions.append(Asset.is_augmented.is_(False))

    result = await db.execute(select(Asset).where(*conditions))
    assets = result.scalars().all()

    captioned = sum(1 for a in assets if a.active_caption_id is not None)
    return {
        "count": len(assets),
        "captioned_count": captioned,
        "uncaptioned_count": len(assets) - captioned,
    }


@router.get("/api/projects/{project_id}/export/validate")
async def validate_export(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    from models.project import Project

    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    result = await db.execute(
        select(Asset).where(
            Asset.project_id == project_id,
            Asset.is_rejected.is_(False),
        )
    )
    assets = result.scalars().all()

    total = len(assets)
    captioned_count = sum(1 for a in assets if a.active_caption_id is not None)
    approved_count = sum(1 for a in assets if a.review_state == ReviewState.APPROVED.value)
    low_quality_count = sum(1 for a in assets if (a.composite_score or 0.0) < 0.3)

    warnings: list[str] = []

    if total == 0:
        warnings.append("No eligible assets in project. Add images before exporting.")
    elif total < 15:
        warnings.append(f"Only {total} images — very small dataset. Recommend 15+ for training.")
    elif total < 30:
        warnings.append(f"Only {total} images — small dataset. Consider adding more.")

    if captioned_count < total:
        uncap = total - captioned_count
        warnings.append(f"{uncap} image(s) have no caption. Consider captioning before export.")

    if approved_count == 0 and total > 0:
        warnings.append("No images have been approved. Consider reviewing images before export.")

    if low_quality_count > 0:
        warnings.append(f"{low_quality_count} image(s) have low quality scores (< 0.3). Consider removing them.")

    return {
        "warnings": warnings,
        "asset_count": total,
        "captioned_count": captioned_count,
        "approved_count": approved_count,
        "low_quality_count": low_quality_count,
    }
