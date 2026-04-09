"""User preferences API — get/update singleton preferences row."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.preferences import UserPreferences

router = APIRouter(prefix="/api", tags=["preferences"])


class PreferencesResponse(BaseModel):
    theme: str
    gallery_zoom: int
    sidebar_collapsed: bool
    default_sort_by: str
    default_sort_dir: str
    auto_analyze_on_import: bool
    auto_caption_on_import: bool
    default_caption_provider: str | None
    default_caption_style: str
    min_quality_for_export: float
    auto_reject_below: float | None
    duplicate_action: str
    duplicate_phash_threshold: int
    duplicate_embedding_threshold: float
    duplicate_face_threshold: float
    extra: dict | None


class PreferencesUpdate(BaseModel):
    theme: str | None = None
    gallery_zoom: int | None = None
    sidebar_collapsed: bool | None = None
    default_sort_by: str | None = None
    default_sort_dir: str | None = None
    auto_analyze_on_import: bool | None = None
    auto_caption_on_import: bool | None = None
    default_caption_provider: str | None = None
    default_caption_style: str | None = None
    min_quality_for_export: float | None = None
    auto_reject_below: float | None = None
    duplicate_action: str | None = None
    duplicate_phash_threshold: int | None = None
    duplicate_embedding_threshold: float | None = None
    duplicate_face_threshold: float | None = None
    extra: dict | None = None


async def _get_or_create(db: AsyncSession) -> UserPreferences:
    """Get the singleton preferences row, creating it if needed."""
    prefs = await db.get(UserPreferences, 1)
    if prefs is None:
        prefs = UserPreferences(id=1)
        db.add(prefs)
        await db.flush()
    return prefs


@router.get("/preferences")
async def get_preferences(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PreferencesResponse:
    prefs = await _get_or_create(db)
    return _prefs_response(prefs)


@router.patch("/preferences")
async def update_preferences(
    body: PreferencesUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PreferencesResponse:
    prefs = await _get_or_create(db)
    update_data = body.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(prefs, key, value)
    await db.flush()
    return _prefs_response(prefs)


def _prefs_response(prefs: UserPreferences) -> PreferencesResponse:
    return PreferencesResponse(
        theme=prefs.theme,
        gallery_zoom=prefs.gallery_zoom,
        sidebar_collapsed=prefs.sidebar_collapsed,
        default_sort_by=prefs.default_sort_by,
        default_sort_dir=prefs.default_sort_dir,
        auto_analyze_on_import=prefs.auto_analyze_on_import,
        auto_caption_on_import=prefs.auto_caption_on_import,
        default_caption_provider=prefs.default_caption_provider,
        default_caption_style=prefs.default_caption_style,
        min_quality_for_export=prefs.min_quality_for_export,
        auto_reject_below=prefs.auto_reject_below,
        duplicate_action=prefs.duplicate_action,
        duplicate_phash_threshold=prefs.duplicate_phash_threshold,
        duplicate_embedding_threshold=prefs.duplicate_embedding_threshold,
        duplicate_face_threshold=prefs.duplicate_face_threshold,
        extra=prefs.extra,
    )
