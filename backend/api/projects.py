"""Projects CRUD router."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.project import Project

router = APIRouter(prefix="/api/projects", tags=["projects"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None
    trigger_word: str | None = None
    subject_type: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    trigger_word: str | None = None
    subject_type: str | None = None
    thumbnail_asset_id: str | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    description: str | None
    trigger_word: str | None
    subject_type: str | None
    asset_count: int
    reviewed_count: int
    flagged_count: int
    rejected_count: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=list[ProjectResponse])
async def list_projects(db: Annotated[AsyncSession, Depends(get_db)]) -> list[ProjectResponse]:
    result = await db.execute(select(Project).order_by(Project.created_at.desc()))
    projects = result.scalars().all()
    return [ProjectResponse.model_validate(p) for p in projects]


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectResponse:
    project = Project(
        id=str(uuid.uuid4()),
        name=body.name,
        description=body.description,
        trigger_word=body.trigger_word,
        subject_type=body.subject_type,
    )
    db.add(project)
    await db.flush()
    return ProjectResponse.model_validate(project)


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectResponse:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return ProjectResponse.model_validate(project)


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: str,
    body: ProjectUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ProjectResponse:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    await db.flush()
    return ProjectResponse.model_validate(project)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    await db.delete(project)


@router.get("/{project_id}/stats")
async def get_project_stats(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    from collections import Counter
    from sqlalchemy import func
    from models.asset import Asset

    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Total count
    total_r = await db.execute(select(func.count(Asset.id)).where(Asset.project_id == project_id))
    total = total_r.scalar() or 0

    approved_r = await db.execute(select(func.count(Asset.id)).where(
        Asset.project_id == project_id, Asset.review_state == "approved"))
    approved = approved_r.scalar() or 0

    rejected_r = await db.execute(select(func.count(Asset.id)).where(
        Asset.project_id == project_id, Asset.review_state == "rejected"))
    rejected = rejected_r.scalar() or 0

    captioned_r = await db.execute(select(func.count(Asset.id)).where(
        Asset.project_id == project_id, Asset.active_caption_id.isnot(None)))
    captioned = captioned_r.scalar() or 0

    embedded_r = await db.execute(select(func.count(Asset.id)).where(
        Asset.project_id == project_id, Asset.analyzed_at.isnot(None)))
    embedded = embedded_r.scalar() or 0

    # Score distributions — fetch all scored assets
    assets_result = await db.execute(
        select(
            Asset.composite_score, Asset.technical_quality, Asset.aesthetic_score,
            Asset.face_count, Asset.shot_type, Asset.dominant_emotion,
        ).where(Asset.project_id == project_id, Asset.composite_score.isnot(None))
    )
    rows = assets_result.all()

    scored = len(rows)
    avg_score = sum(r.composite_score for r in rows) / scored if scored else 0.0
    high_quality = sum(1 for r in rows if r.composite_score >= 0.7)
    low_quality = sum(1 for r in rows if r.composite_score < 0.4)

    # Score histogram buckets (0–10%, 10–20%, … 90–100%)
    score_hist = [0] * 10
    for r in rows:
        bucket = min(int(r.composite_score * 10), 9)
        score_hist[bucket] += 1

    face_images = sum(1 for r in rows if (r.face_count or 0) > 0)
    multi_face = sum(1 for r in rows if (r.face_count or 0) > 1)

    shot_counts = Counter(r.shot_type for r in rows if r.shot_type)
    emotion_counts = Counter(r.dominant_emotion for r in rows if r.dominant_emotion)

    return {
        "total": total,
        "approved": approved,
        "rejected": rejected,
        "pending": total - approved - rejected,
        "captioned": captioned,
        "caption_coverage_pct": round(captioned / total * 100, 1) if total > 0 else 0,
        "scored": scored,
        "embedded": embedded,
        "avg_score": round(avg_score, 3),
        "high_quality": high_quality,
        "low_quality": low_quality,
        "score_histogram": [
            {"bucket": f"{i * 10}-{i * 10 + 10}%", "count": score_hist[i]}
            for i in range(10)
        ],
        "face_images": face_images,
        "multi_face": multi_face,
        "shot_types": [{"type": k, "count": v} for k, v in shot_counts.most_common()],
        "emotions": [{"emotion": k, "count": v} for k, v in emotion_counts.most_common(6)],
    }
