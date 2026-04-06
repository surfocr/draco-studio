"""Admin maintenance endpoints."""
from __future__ import annotations

import logging
import shutil
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/clear-thumbnails")
async def clear_thumbnails() -> dict:
    """Delete all generated thumbnail files from the storage directory."""
    thumbs_dir = settings.storage_path / "thumbnails"
    deleted = 0
    if thumbs_dir.exists():
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
    # VACUUM must run outside a transaction
    await db.execute(text("VACUUM"))
    logger.info("Database vacuumed")
    return {"status": "ok"}
