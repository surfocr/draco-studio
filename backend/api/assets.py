"""
Assets router — CRUD, ingest, thumbnails, streaming originals.
"""
from __future__ import annotations

import asyncio
import io
import logging
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from typing import Optional
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models.asset import Asset, ReviewState, ShotType
from services.ingest import ingest_directory, ingest_files

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["assets"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class AssetSummary(BaseModel):
    id: str
    filename: str
    width: int | None
    height: int | None
    composite_score: float | None
    face_count: int
    review_state: str
    is_flagged: bool
    is_rejected: bool
    is_augmented: bool
    shot_type: str
    thumbnail_path: str | None
    active_caption_id: str | None
    duplicate_cluster_id: str | None
    trueskill_mu: float
    imported_at: Any  # datetime

    model_config = {"from_attributes": True}


class AssetDetail(AssetSummary):
    filepath: str
    file_size: int | None
    mime_type: str | None
    sha256_hash: str | None
    phash: str | None
    analyzed_at: Any | None
    technical_quality: float | None
    aesthetic_score: float | None
    face_quality: float | None
    training_usefulness: float | None
    score_breakdown: dict | None
    primary_face_bbox: dict | None
    head_pose_yaw: float | None
    head_pose_pitch: float | None
    head_pose_roll: float | None
    age_estimate: float | None
    gender_estimate: str | None
    dominant_emotion: str | None
    gaze_direction: str | None
    is_indoor: bool | None
    scene_class: str | None
    scene_tags: list[str] | None
    object_tags: list[str] | None
    caption_provider: str | None
    augmentation_source_id: str | None
    trueskill_sigma: float
    elo_rating: float
    ranking_comparisons_count: int

    model_config = {"from_attributes": True}


class AssetUpdate(BaseModel):
    review_state: str | None = None
    is_flagged: bool | None = None
    is_rejected: bool | None = None
    rejection_reason: str | None = None
    shot_type: str | None = None


class IngestDirectoryRequest(BaseModel):
    directory_path: str
    recursive: bool = True
    queue_analysis: bool = True


class AssetListResponse(BaseModel):
    items: list[AssetSummary]
    total: int
    page: int
    page_size: int
    has_next: bool


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/projects/{project_id}/assets", response_model=AssetListResponse)
async def list_assets(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    sort_by: str = Query("imported_at"),
    sort_dir: str = Query("desc"),
    min_score: float | None = Query(None),
    max_score: float | None = Query(None),
    review_state: str | None = Query(None),
    shot_type: str | None = Query(None),
    has_face: bool | None = Query(None),
    is_flagged: bool | None = Query(None),
    is_rejected: bool | None = Query(None),
    identity_cluster_id: str | None = Query(None),
    has_caption: bool | None = Query(None),
    has_duplicate: bool | None = Query(None),
    search: str | None = Query(None),
) -> AssetListResponse:
    query = select(Asset).where(Asset.project_id == project_id)

    # Filters
    if min_score is not None:
        query = query.where(Asset.composite_score >= min_score)
    if max_score is not None:
        query = query.where(Asset.composite_score <= max_score)
    if review_state:
        query = query.where(Asset.review_state == review_state)
    if shot_type:
        query = query.where(Asset.shot_type == shot_type)
    if has_face is not None:
        if has_face:
            query = query.where(Asset.face_count > 0)
        else:
            query = query.where(Asset.face_count == 0)
    if is_flagged is not None:
        query = query.where(Asset.is_flagged == is_flagged)
    if is_rejected is not None:
        query = query.where(Asset.is_rejected == is_rejected)
    if identity_cluster_id:
        query = query.where(Asset.identity_cluster_id == identity_cluster_id)
    if has_caption is not None:
        if has_caption:
            query = query.where(Asset.active_caption_id.isnot(None))
        else:
            query = query.where(Asset.active_caption_id.is_(None))
    if has_duplicate is not None:
        if has_duplicate:
            query = query.where(Asset.duplicate_cluster_id.isnot(None))
        else:
            query = query.where(Asset.duplicate_cluster_id.is_(None))
    if search:
        query = query.where(Asset.filename.ilike(f"%{search}%"))

    # Total count
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Sorting
    sort_col_map = {
        "imported_at": Asset.imported_at,
        "composite_score": Asset.composite_score,
        "aesthetic_score": Asset.aesthetic_score,
        "face_quality": Asset.face_quality,
        "technical_quality": Asset.technical_quality,
        "filename": Asset.filename,
        "trueskill_mu": Asset.trueskill_mu,
        "analyzed_at": Asset.analyzed_at,
    }
    sort_col = sort_col_map.get(sort_by, Asset.imported_at)
    if sort_dir == "asc":
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc().nullslast())

    # Pagination
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    assets = result.scalars().all()

    return AssetListResponse(
        items=[AssetSummary.model_validate(a) for a in assets],
        total=total,
        page=page,
        page_size=page_size,
        has_next=(offset + len(assets)) < total,
    )


@router.get("/projects/{project_id}/assets/search")
async def search_assets(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    q: str = Query(""),
    shot_type: str | None = Query(None),
    min_score: float | None = Query(None),
    max_score: float | None = Query(None),
    has_face: bool | None = Query(None),
    expression: str | None = Query(None),
    review_state: str | None = Query(None),
    is_augmented: bool | None = Query(None),
    sort_by: str = Query("composite_score"),
    sort_dir: str = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
) -> dict:
    """Full-text + faceted search endpoint for assets."""
    query = select(Asset).where(Asset.project_id == project_id)

    if q:
        query = query.where(Asset.filename.ilike(f"%{q}%"))
    if shot_type:
        query = query.where(Asset.shot_type == shot_type)
    if min_score is not None:
        query = query.where(Asset.composite_score >= min_score)
    if max_score is not None:
        query = query.where(Asset.composite_score <= max_score)
    if has_face is True:
        query = query.where(Asset.face_count > 0)
    if has_face is False:
        query = query.where(Asset.face_count == 0)
    if expression:
        query = query.where(Asset.dominant_emotion == expression)
    if review_state:
        query = query.where(Asset.review_state == review_state)
    if is_augmented is not None:
        query = query.where(Asset.is_augmented == is_augmented)

    sort_col_map = {
        "composite_score": Asset.composite_score,
        "imported_at": Asset.imported_at,
        "aesthetic_score": Asset.aesthetic_score,
        "technical_quality": Asset.technical_quality,
        "filename": Asset.filename,
        "trueskill_mu": Asset.trueskill_mu,
    }
    sort_col = sort_col_map.get(sort_by, Asset.composite_score)
    if sort_dir == "asc":
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc().nullslast())

    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    assets = result.scalars().all()

    return {
        "assets": [
            {
                "id": str(a.id),
                "filename": a.filename,
                "thumbnail_url": f"/api/assets/{a.id}/thumbnail",
                "composite_score": a.composite_score,
                "face_count": a.face_count,
                "shot_type": a.shot_type,
                "dominant_emotion": a.dominant_emotion,
                "review_state": a.review_state,
                "is_augmented": a.is_augmented,
                "width": a.width,
                "height": a.height,
            }
            for a in assets
        ],
        "page": page,
        "page_size": page_size,
    }


@router.get("/assets/search")
async def search_assets_flat(
    db: Annotated[AsyncSession, Depends(get_db)],
    project_id: int = Query(...),
    min_score: Optional[float] = Query(None),
    max_score: Optional[float] = Query(None),
    shot_type: Optional[str] = Query(None),
    expression: Optional[str] = Query(None),
    review_state: Optional[str] = Query(None),
    has_caption: Optional[bool] = Query(None),
    is_augmented: Optional[bool] = Query(None),
    limit: int = Query(100),
    offset: int = Query(0),
) -> list[dict]:
    """Flat search/filter endpoint with project_id as query param."""
    query = select(Asset).where(Asset.project_id == project_id)
    if min_score is not None:
        query = query.where(Asset.composite_score >= min_score)
    if max_score is not None:
        query = query.where(Asset.composite_score <= max_score)
    if shot_type:
        query = query.where(Asset.shot_type == shot_type)
    if expression:
        query = query.where(Asset.dominant_emotion == expression)
    if review_state:
        query = query.where(Asset.review_state == review_state)
    if has_caption is not None:
        if has_caption:
            query = query.where(Asset.active_caption_id.isnot(None))
        else:
            query = query.where(Asset.active_caption_id.is_(None))
    if is_augmented is not None:
        query = query.where(Asset.is_augmented == is_augmented)
    query = query.offset(offset).limit(limit)
    result = await db.execute(query)
    assets = result.scalars().all()
    return [
        {
            "id": str(a.id),
            "filename": a.filename,
            "thumbnail_url": f"/api/assets/{a.id}/thumbnail",
            "composite_score": a.composite_score,
            "shot_type": a.shot_type,
            "dominant_emotion": a.dominant_emotion,
            "review_state": a.review_state,
            "is_augmented": a.is_augmented,
        }
        for a in assets
    ]


@router.post("/projects/{project_id}/assets/ingest", status_code=status.HTTP_202_ACCEPTED)
async def ingest_upload(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    files: list[UploadFile] = File(...),
    queue_analysis: bool = Form(True),
) -> dict:
    """Upload files directly. Returns job_id for progress tracking."""
    from workers.job_queue import get_job_queue

    # Save uploaded files to temp dir
    tmp_dir = tempfile.mkdtemp(prefix="draco_ingest_")
    file_paths = []
    for upload in files:
        tmp_path = Path(tmp_dir) / (upload.filename or "unknown")
        content = await upload.read()
        tmp_path.write_bytes(content)
        file_paths.append(str(tmp_path))

    # Submit async ingest job — open a fresh session inside the worker so it is
    # not tied to the request-scoped session that FastAPI closes on 202 return.
    queue = get_job_queue()
    _project_id = project_id
    _queue_analysis = queue_analysis

    async def _run_ingest() -> dict:
        from database import AsyncSessionLocal
        results: dict = {"created": [], "errors": [], "duplicates": 0}
        async with AsyncSessionLocal() as worker_db:
            async for progress in ingest_files(file_paths, _project_id, worker_db, _queue_analysis):
                results["created"] = progress.assets_created
                results["errors"] = progress.errors
                results["duplicates"] = progress.duplicates_found
            await worker_db.commit()
        return results

    job_id = await queue.submit(_run_ingest)
    return {"job_id": job_id, "file_count": len(file_paths)}


@router.post(
    "/projects/{project_id}/assets/ingest-directory",
    status_code=status.HTTP_202_ACCEPTED,
)
async def ingest_dir(
    project_id: str,
    body: IngestDirectoryRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Ingest all images from a local directory path."""
    requested = Path(body.directory_path).resolve()
    if not requested.is_dir():
        raise HTTPException(status_code=400, detail="Directory not found")
    ingest_root = settings.data_dir
    if not requested.is_relative_to(ingest_root):
        raise HTTPException(
            status_code=400,
            detail=f"Directory must be within the data directory ({ingest_root})",
        )

    from workers.job_queue import get_job_queue

    queue = get_job_queue()

    _dir_project_id = project_id
    _dir_body = body

    async def _run() -> dict:
        from database import AsyncSessionLocal
        results: dict = {"created": [], "errors": [], "duplicates": 0}
        async with AsyncSessionLocal() as worker_db:
            async for progress in ingest_directory(
                _dir_body.directory_path, _dir_project_id, worker_db,
                _dir_body.recursive, _dir_body.queue_analysis,
            ):
                results["created"] = progress.assets_created
                results["errors"] = progress.errors
                results["duplicates"] = progress.duplicates_found
            await worker_db.commit()
        return results

    job_id = await queue.submit(_run)
    return {"job_id": job_id, "directory": body.directory_path}


@router.get("/assets/{asset_id}", response_model=AssetDetail)
async def get_asset(
    asset_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AssetDetail:
    asset = await db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    return AssetDetail.model_validate(asset)


@router.patch("/assets/{asset_id}", response_model=AssetSummary)
async def update_asset(
    asset_id: str,
    body: AssetUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AssetSummary:
    asset = await db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    if body.review_state is not None:
        if body.review_state not in {s.value for s in ReviewState}:
            raise HTTPException(status_code=400, detail=f"Invalid review_state: {body.review_state}")
        asset.review_state = body.review_state
    if body.is_flagged is not None:
        asset.is_flagged = body.is_flagged
    if body.is_rejected is not None:
        asset.is_rejected = body.is_rejected
    if body.rejection_reason is not None:
        asset.rejection_reason = body.rejection_reason
    if body.shot_type is not None:
        asset.shot_type = body.shot_type

    await db.flush()
    return AssetSummary.model_validate(asset)


@router.delete("/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    asset_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    asset = await db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    from providers.registry import get_registry
    registry = get_registry()
    storage = registry.get("storage", "local")
    if storage:
        await storage.delete_asset(asset.filepath, asset_id)

    await db.delete(asset)


@router.get("/assets/{asset_id}/thumbnail")
async def serve_thumbnail(
    asset_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    size: int = Query(512),
) -> FileResponse:
    asset = await db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    thumb_path = asset.thumbnail_path if size >= 256 else asset.thumbnail_small_path
    if not thumb_path or not Path(thumb_path).exists():
        # Fall back to original
        if not asset.filepath or not Path(asset.filepath).exists():
            raise HTTPException(status_code=404, detail="Thumbnail not found")
        return FileResponse(asset.filepath, media_type=asset.mime_type or "image/jpeg")

    return FileResponse(thumb_path, media_type="image/webp")


@router.get("/assets/{asset_id}/original")
async def serve_original(
    asset_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileResponse:
    asset = await db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    if not asset.filepath or not Path(asset.filepath).exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        asset.filepath,
        media_type=asset.mime_type or "image/jpeg",
        filename=asset.filename,
    )


@router.get("/assets/{asset_id}/explain")
async def explain_asset_score(
    asset_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Return AI judge score breakdown for a single asset."""
    asset = await db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    try:
        from services.ai_judge import get_ai_judge
        judge = get_ai_judge()
        result = await judge.score_image(asset.filepath or "", str(asset.id))
        return {
            "composite": result.composite,
            "dimensions": [
                {"key": "technical_quality", "label": "Technical Quality", "score": result.technical_quality.score, "weight": 1.0, "rationale": result.technical_quality.reason},
                {"key": "aesthetic_quality", "label": "Aesthetic Quality", "score": result.aesthetic_quality.score, "weight": 1.0, "rationale": result.aesthetic_quality.reason},
                {"key": "face_clarity", "label": "Face Clarity", "score": result.face_clarity.score, "weight": 1.0, "rationale": result.face_clarity.reason},
                {"key": "pose_usefulness", "label": "Pose", "score": result.pose_usefulness.score, "weight": 0.8, "rationale": result.pose_usefulness.reason},
                {"key": "expression_quality", "label": "Expression", "score": result.expression_quality.score, "weight": 0.8, "rationale": result.expression_quality.reason},
                {"key": "background_usefulness", "label": "Background", "score": result.background_usefulness.score, "weight": 0.6, "rationale": result.background_usefulness.reason},
                {"key": "uniqueness", "label": "Uniqueness", "score": result.uniqueness.score, "weight": 0.7, "rationale": result.uniqueness.reason},
                {"key": "training_value", "label": "Training Value", "score": result.training_value.score, "weight": 1.0, "rationale": result.training_value.reason},
            ],
            "summary": f"Recommendation: {result.recommendation}. Confidence: {result.confidence}." + (f" {result.review_reason}" if result.review_reason else ""),
            "recommendations": result.weaknesses,
            "judge_provider": result.provider_used,
        }
    except Exception as e:
        return {
            "composite": asset.composite_score or 0,
            "dimensions": [
                {"key": "technical_quality", "label": "Technical Quality", "score": asset.technical_quality or 0, "weight": 1.0},
                {"key": "aesthetic_score", "label": "Aesthetic", "score": asset.aesthetic_score or 0, "weight": 1.0},
                {"key": "face_quality", "label": "Face Quality", "score": asset.face_quality or 0, "weight": 1.0},
            ],
            "summary": "Scores from stored analysis.",
            "judge_provider": "stored",
            "error": str(e),
        }


@router.post("/assets/{asset_id}/reanalyze", status_code=status.HTTP_202_ACCEPTED)
async def reanalyze_asset(
    asset_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    asset = await db.get(Asset, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    from workers.tasks import queue_analysis_task
    job_id = await queue_analysis_task(asset_id)
    return {"job_id": job_id}


@router.post("/projects/{project_id}/assets/bulk-action", status_code=status.HTTP_200_OK)
async def bulk_action(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    action: str = Form(...),
    asset_ids: list[str] = Form(...),
) -> dict:
    """Perform a bulk action on multiple assets."""
    valid_actions = {"approve", "reject", "flag", "unflag", "delete", "reanalyze"}
    if action not in valid_actions:
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")

    affected = 0
    for asset_id in asset_ids:
        asset = await db.get(Asset, asset_id)
        if not asset or asset.project_id != project_id:
            continue

        if action == "approve":
            asset.review_state = ReviewState.APPROVED.value
            asset.is_rejected = False
        elif action == "reject":
            asset.review_state = ReviewState.REJECTED.value
            asset.is_rejected = True
        elif action == "flag":
            asset.is_flagged = True
        elif action == "unflag":
            asset.is_flagged = False
        elif action == "delete":
            await db.delete(asset)
        elif action == "reanalyze":
            from workers.tasks import queue_analysis_task
            await queue_analysis_task(asset_id)

        affected += 1

    await db.flush()
    return {"affected": affected, "action": action}
