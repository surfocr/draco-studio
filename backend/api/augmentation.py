"""Augmentation router."""
from __future__ import annotations

from typing import Annotated
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from services.augmentation import AugmentationService

router = APIRouter(tags=["augmentation"])
_service = AugmentationService()


class OutpaintRequest(BaseModel):
    target_width: int
    target_height: int
    provider: str = "auto"
    prompt: str | None = None


class AutoFitRequest(BaseModel):
    asset_ids: list[str] | None = None
    target_width: int
    target_height: int
    provider: str = "auto"
    prompt: str | None = None


class ExecutePlanRequest(BaseModel):
    plan_item_id: str
    provider: str = "auto"


@router.get("/api/projects/{project_id}/augmentation/plan")
async def get_augmentation_plan(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    from models.project import Project

    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    plans = await _service.plan_expansions(project_id, db)
    return {
        "project_id": project_id,
        "plans": [
            {
                "id": p.id,
                "operation": p.operation,
                "reason": p.reason,
                "gap_addressed": p.gap_addressed,
                "source_asset_id": p.source_asset_id,
                "estimated_benefit": p.estimated_benefit,
                "params": p.params,
                "priority": p.priority,
            }
            for p in plans
        ],
    }


@router.post("/api/assets/{asset_id}/outpaint")
async def outpaint_asset(
    asset_id: str,
    body: OutpaintRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    try:
        job = await _service.outpaint_to_ratio(
            asset_id,
            body.target_width,
            body.target_height,
            db,
            provider_name=body.provider,
            prompt=body.prompt,
        )
        return {
            "result_id": job.id,
            "status": job.status,
            "output_path": job.output_path,
            "operation": job.augmentation_type,
            "provider": job.provider,
            "error": job.error_message,
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/projects/{project_id}/augmentation/auto-fit")
async def auto_fit_assets(
    project_id: str,
    body: AutoFitRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    asset_count = await _service.resolve_auto_fit_asset_count(
        project_id=project_id,
        asset_ids=body.asset_ids or [],
        db=db,
    )
    if asset_count == 0:
        raise HTTPException(status_code=400, detail="No eligible assets available for augmentation")

    job_id = await _service.auto_fit_assets(
        body.asset_ids or [],
        body.target_width,
        body.target_height,
        project_id=project_id,
        provider_name=body.provider,
        prompt=body.prompt,
    )
    return {"job_id": job_id, "asset_count": asset_count}


@router.get("/api/augmentation/results/{result_id}")
async def get_augmentation_result(
    result_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    job = await _service.get_result(result_id, db)
    if not job:
        raise HTTPException(status_code=404, detail="Result not found")
    return {
        "id": job.id,
        "source_asset_id": job.source_asset_id,
        "output_path": job.output_path,
        "operation": job.augmentation_type,
        "provider": job.provider,
        "status": job.status,
        "before_score": job.before_score,
        "after_score": job.after_score,
        "identity_preserved": job.identity_preserved,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "params_used": job.parameters or {},
        "error": job.error_message,
    }


@router.post("/api/augmentation/results/{result_id}/approve")
async def approve_result(
    result_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    try:
        asset = await _service.approve_result(result_id, db)
        return {"status": "approved", "new_asset_id": asset.id}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/augmentation/results/{result_id}/reject")
async def reject_result(
    result_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    await _service.reject_result(result_id, db)
    return {"status": "rejected"}


@router.get("/api/augmentation/results")
async def list_pending_results(
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: str | None = Query(default=None),
) -> dict:
    jobs = await _service.list_pending_results(db, project_id=project_id)
    return {
        "results": [
            {
                "id": j.id,
                "source_asset_id": j.source_asset_id,
                "output_path": j.output_path,
                "operation": j.augmentation_type,
                "provider": j.provider,
                "status": j.status,
                "before_score": j.before_score,
                "after_score": j.after_score,
                "identity_preserved": j.identity_preserved,
                "created_at": j.created_at.isoformat() if j.created_at else None,
            }
            for j in jobs
        ]
    }


@router.get("/api/augmentation/preview/{result_id}")
async def get_augmentation_preview(
    result_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileResponse:
    job = await _service.get_result(result_id, db)
    if not job or not job.output_path:
        raise HTTPException(status_code=404, detail="Preview not found")
    resolved = Path(job.output_path).resolve()
    # Restrict preview to managed storage and ComfyUI output directories
    from config import settings
    allowed_roots = [
        Path(settings.STORAGE_PATH).resolve(),
        Path(settings.DATA_DIR).resolve(),
    ]
    if not any(root in resolved.parents or resolved == root for root in allowed_roots):
        raise HTTPException(status_code=403, detail="Preview path outside managed storage")
    if not resolved.exists():
        raise HTTPException(status_code=404, detail="Preview file not found")
    return FileResponse(str(resolved))
