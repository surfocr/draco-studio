"""Admin maintenance endpoints."""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import engine, get_db
from services.asset_state import AssetStateService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/clear-thumbnails")
async def clear_thumbnails() -> dict:
    """Delete all generated thumbnail files from the storage directory.

    Thumbnails are stored at storage_path/{project_id}/thumbnails/,
    so we scan all project directories for thumbnail subdirectories.
    """
    storage = settings.storage_path
    deleted = 0
    if storage.exists():
        for project_dir in storage.iterdir():
            if not project_dir.is_dir():
                continue
            thumbs_dir = project_dir / "thumbnails"
            if not thumbs_dir.exists():
                continue
            for thumb in thumbs_dir.iterdir():
                try:
                    thumb.unlink()
                    deleted += 1
                except Exception as exc:
                    logger.warning("Could not delete thumbnail %s: %s", thumb, exc)
    logger.info("Cleared %d thumbnail(s)", deleted)
    return {"deleted": deleted}


@router.post("/vacuum")
async def vacuum_db(db: Annotated[AsyncSession, Depends(get_db)]) -> dict:
    """Run VACUUM on the SQLite database to reclaim space."""
    await db.rollback()
    async with engine.connect() as conn:
        await conn.execution_options(isolation_level="AUTOCOMMIT").execute(text("VACUUM"))
    logger.info("Database vacuumed")
    return {"status": "ok"}


@router.get("/storage-info")
async def storage_info() -> dict:
    """Return backend-owned storage locations for the active install."""
    return {
        "storage_path": str(settings.storage_path),
        "data_dir": str(settings.data_dir),
        "qdrant_path": str(settings.QDRANT_PATH),
    }


@router.post("/projects/{project_id}/recount")
async def recount_project(project_id: str, db: Annotated[AsyncSession, Depends(get_db)]) -> dict:
    """Repair denormalized project counters from live asset rows."""
    try:
        counts = await AssetStateService.sync_project_counters(project_id, db)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    logger.info("Recounted project %s: %s", project_id, counts)
    return {"project_id": project_id, **counts}
