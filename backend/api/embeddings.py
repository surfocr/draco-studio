"""Embedding indexing and status API endpoints."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db

router = APIRouter(prefix="/api/embeddings", tags=["embeddings"])


class IndexProjectRequest(BaseModel):
    project_id: str
    force: bool = False


@router.post("/index")
async def index_project(
    req: IndexProjectRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Queue CLIP embedding for all un-analyzed assets in a project (background)."""
    from services.embedding_service import index_project as _index
    background_tasks.add_task(_index, req.project_id, db, req.force)
    return {"status": "queued", "project_id": req.project_id, "force": req.force}


@router.post("/index_asset/{asset_id}")
async def index_single_asset(
    asset_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Compute and store the CLIP embedding for a single asset immediately."""
    from services.embedding_service import index_asset
    ok = await index_asset(asset_id, db)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Asset {asset_id} not found or embedding failed",
        )
    return {"success": True, "asset_id": asset_id}


@router.get("/status/{project_id}")
async def embedding_status(
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Get embedding coverage stats for a project."""
    from services.embedding_service import get_embedding_status
    return await get_embedding_status(project_id, db)
