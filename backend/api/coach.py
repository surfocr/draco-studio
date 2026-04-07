"""Dataset Coach router."""
from __future__ import annotations

import dataclasses
import time
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from services.asset_state import AssetStateService
from services.coach import DatasetCoach

router = APIRouter(prefix="/api/projects", tags=["coach"])

# Simple in-memory cache: { (project_id, trigger_words_tuple): (timestamp, CoachReport) }
_report_cache: dict[tuple, tuple[float, object]] = {}
_CACHE_TTL_SECONDS = 300  # 5 minutes


def _invalidate_project_cache(project_id: str) -> None:
    stale_keys = [key for key in _report_cache if key and key[0] == project_id]
    for key in stale_keys:
        _report_cache.pop(key, None)


class ApplyActionRequest(BaseModel):
    asset_ids: list[str]


class RemoveCandidatesResponse(BaseModel):
    items: list[dict]
    total: int


@router.get("/{project_id}/coach/analyze")
async def analyze_project(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    trigger_words: str | None = Query(default=None, description="Comma-separated trigger words"),
) -> dict:
    """Run full dataset analysis synchronously. Returns CoachReport as JSON."""
    from models.project import Project
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    tw_list: list[str] | None = None
    if trigger_words:
        tw_list = [w.strip() for w in trigger_words.split(",") if w.strip()]

    coach = DatasetCoach()
    report = await coach.analyze(project_id, db, trigger_words=tw_list)

    # Cache keyed by (project_id, normalised trigger words) so different
    # trigger-word sets don't collide.
    cache_key = (project_id, tuple(sorted(tw_list or [])))
    _report_cache[cache_key] = (time.monotonic(), report)

    return dataclasses.asdict(report)


@router.get("/{project_id}/coach/report")
async def get_cached_report(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    trigger_words: str | None = Query(default=None, description="Comma-separated trigger words"),
) -> dict:
    """Alias for analyze — returns cached report if fresh (< 5 min old)."""
    tw_list = [w.strip() for w in trigger_words.split(",") if w.strip()] if trigger_words else []
    cache_key = (project_id, tuple(sorted(tw_list)))
    cached = _report_cache.get(cache_key)
    if cached is not None:
        ts, report = cached
        if time.monotonic() - ts < _CACHE_TTL_SECONDS:
            return dataclasses.asdict(report)

    # Cache miss — run full analysis
    return await analyze_project(project_id, db, trigger_words=trigger_words)


@router.post("/{project_id}/coach/apply/{action}")
async def apply_coach_action(
    project_id: str,
    action: str,
    body: ApplyActionRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Apply an auto-fix action to a list of assets.

    Actions:
    - remove_low_quality: sets is_rejected=True for affected assets
    - remove_exact_duplicates: sets is_rejected=True keeping one per sha256
    - normalize_captions: normalizes active captions for the selected assets
    """
    from models.asset import Asset

    valid_actions = {"remove_low_quality", "remove_exact_duplicates", "normalize_captions"}
    if action not in valid_actions:
        raise HTTPException(status_code=400, detail=f"Unknown action '{action}'. Valid: {', '.join(valid_actions)}")

    from models.project import Project
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    affected = 0

    if action == "remove_low_quality":
        if not body.asset_ids:
            raise HTTPException(status_code=400, detail="asset_ids required for remove_low_quality")
        result = await db.execute(
            select(Asset).where(
                Asset.project_id == project_id,
                Asset.id.in_(body.asset_ids),
            )
        )
        assets = result.scalars().all()
        for a in assets:
            if not a.is_rejected:
                await AssetStateService.reject_asset(
                    a,
                    db,
                    rejection_reason="Rejected by dataset coach: remove_low_quality",
                )
                affected += 1
        if affected:
            await AssetStateService.sync_project_counters(project_id, db)
        await db.commit()
        _invalidate_project_cache(project_id)

    elif action == "remove_exact_duplicates":
        # Load all project assets (or the provided subset)
        if body.asset_ids:
            result = await db.execute(
                select(Asset).where(
                    Asset.project_id == project_id,
                    Asset.id.in_(body.asset_ids),
                    Asset.is_rejected.is_(False),
                )
            )
        else:
            result = await db.execute(
                select(Asset).where(
                    Asset.project_id == project_id,
                    Asset.is_rejected.is_(False),
                )
            )
        assets = result.scalars().all()

        # Group by sha256 — keep the one with highest composite_score
        sha_groups: dict[str, list[Asset]] = {}
        no_hash: list[Asset] = []
        for a in assets:
            if a.sha256_hash:
                sha_groups.setdefault(a.sha256_hash, []).append(a)
            else:
                no_hash.append(a)

        for sha, group in sha_groups.items():
            if len(group) <= 1:
                continue
            # Sort by composite_score descending — keep first
            group_sorted = sorted(group, key=lambda x: x.composite_score or 0.0, reverse=True)
            for dup in group_sorted[1:]:
                await AssetStateService.reject_asset(
                    dup,
                    db,
                    rejection_reason="Rejected by dataset coach: exact duplicate",
                )
                affected += 1

        if affected:
            await AssetStateService.sync_project_counters(project_id, db)
        await db.commit()
        _invalidate_project_cache(project_id)

    elif action == "normalize_captions":
        from services.caption import get_caption_service
        if body.asset_ids:
            result = await db.execute(
                select(Asset.id).where(
                    Asset.project_id == project_id,
                    Asset.id.in_(body.asset_ids),
                    Asset.active_caption_id.isnot(None),
                )
            )
        else:
            result = await db.execute(
                select(Asset.id).where(
                    Asset.project_id == project_id,
                    Asset.active_caption_id.isnot(None),
                )
            )
        asset_ids = [row[0] for row in result.all()]
        affected = await get_caption_service().normalize(asset_ids, db) if asset_ids else 0
        await db.commit()
        _invalidate_project_cache(project_id)

    return {"affected": affected, "action": action}


@router.get("/{project_id}/coach/remove-candidates")
async def get_remove_candidates(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> dict:
    """Return paginated list of remove candidates (worst scoring + duplicates)."""
    from models.asset import Asset
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
    all_assets = result.scalars().all()

    def _sort_key(a: Asset) -> float:
        score = a.composite_score or 0.0
        if a.duplicate_cluster_id:
            score -= 0.3
        return score

    sorted_assets = sorted(all_assets, key=_sort_key)
    total = len(sorted_assets)

    offset = (page - 1) * page_size
    page_assets = sorted_assets[offset: offset + page_size]

    items = [
        {
            "id": a.id,
            "filename": a.filename,
            "filepath": a.filepath,
            "composite_score": a.composite_score,
            "technical_quality": a.technical_quality,
            "duplicate_cluster_id": a.duplicate_cluster_id,
            "duplicate_type": a.duplicate_type,
            "review_state": a.review_state,
            "shot_type": a.shot_type,
            "face_count": a.face_count,
            "is_flagged": a.is_flagged,
        }
        for a in page_assets
    ]

    return {"items": items, "total": total}
