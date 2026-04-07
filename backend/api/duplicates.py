"""
Duplicates router backed by the shared duplicate-detection service.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.asset import Asset
from workers.tasks import queue_duplicate_scan

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["duplicates"])


class DuplicateImageResponse(BaseModel):
    id: str
    filepath: str
    thumbnail_url: str
    score: float
    quality_score: float | None
    keep: bool


class DuplicateClusterResponse(BaseModel):
    id: str
    cluster_type: str
    image_count: int
    images: list[DuplicateImageResponse]
    best_id: str


class DuplicateListResponse(BaseModel):
    clusters: list[DuplicateClusterResponse]
    total_clusters: int
    total_duplicates: int


def _quality_tuple(asset: Asset) -> tuple[float, float, float, float, float]:
    return (
        float(asset.composite_score or 0.0),
        float(asset.training_usefulness or 0.0),
        float(asset.technical_quality or 0.0),
        float(asset.face_quality or 0.0),
        float((asset.width or 0) * (asset.height or 0)),
    )


def _representative_id(cluster_assets: list[Asset]) -> str:
    best = max(
        cluster_assets,
        key=lambda asset: (_quality_tuple(asset), asset.imported_at or datetime.min),
    )
    return str(best.id)


def _asset_payload(asset: Asset, *, keep: bool, score: float) -> DuplicateImageResponse:
    return DuplicateImageResponse(
        id=str(asset.id),
        filepath=asset.filepath,
        thumbnail_url=f"/api/assets/{asset.id}/thumbnail",
        score=round(float(score), 4),
        quality_score=asset.composite_score,
        keep=keep,
    )


@router.post(
    "/projects/{project_id}/duplicates/scan",
    status_code=status.HTTP_202_ACCEPTED,
)
async def scan_duplicates(project_id: str) -> dict:
    job_id = await queue_duplicate_scan(project_id)
    return {"job_id": job_id}


@router.get("/projects/{project_id}/duplicates", response_model=DuplicateListResponse)
async def get_duplicate_clusters(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DuplicateListResponse:
    """Returns duplicate clusters for a project.

    If no stored cluster data exists (first call or after a reset), an inline
    exact-hash scan is performed automatically.  Full embedding / face scans
    should be triggered via POST /duplicates/scan.
    """

    # Check whether any asset in this project has cluster data already
    any_clustered_result = await db.execute(
        select(Asset).where(
            Asset.project_id == project_id,
            Asset.is_rejected.is_(False),
            Asset.duplicate_cluster_id.isnot(None),
        ).limit(1)
    )
    has_stored_clusters = any_clustered_result.scalar_one_or_none() is not None

    if not has_stored_clusters:
        # Run a fast exact-hash scan inline so first-time callers see results
        # without having to explicitly trigger a background scan.
        try:
            from services.duplicate import find_duplicates
            await find_duplicates(project_id, db, stages=["exact"])
            await db.flush()
        except Exception as exc:
            logger.warning("Auto-scan failed for project %s: %s", project_id, exc)

    # Fetch assets that have a duplicate_cluster_id assigned
    asset_result = await db.execute(
        select(Asset).where(
            Asset.project_id == project_id,
            Asset.is_rejected.is_(False),
            Asset.duplicate_cluster_id.isnot(None),
        )
    )
    assets = asset_result.scalars().all()

    # Group by cluster
    clusters_map: dict[str, list[Asset]] = {}
    cluster_types: dict[str, str] = {}
    for asset in assets:
        cid = str(asset.duplicate_cluster_id)
        clusters_map.setdefault(cid, []).append(asset)
        if asset.duplicate_type:
            cluster_types[cid] = asset.duplicate_type

    response_clusters: list[DuplicateClusterResponse] = []
    for cid, cluster_assets in clusters_map.items():
        if len(cluster_assets) < 2:
            continue

        best_id = _representative_id(cluster_assets)
        images = [
            _asset_payload(
                asset,
                keep=str(asset.id) == best_id,
                score=float(asset.composite_score or 0.0),
            )
            for asset in sorted(cluster_assets, key=_quality_tuple, reverse=True)
        ]
        response_clusters.append(
            DuplicateClusterResponse(
                id=cid,
                cluster_type=cluster_types.get(cid, "unknown"),
                image_count=len(images),
                images=images,
                best_id=best_id,
            )
        )

    response_clusters.sort(key=lambda cluster: (cluster.image_count, cluster.cluster_type), reverse=True)
    total_duplicates = sum(max(cluster.image_count - 1, 0) for cluster in response_clusters)

    return DuplicateListResponse(
        clusters=response_clusters,
        total_clusters=len(response_clusters),
        total_duplicates=total_duplicates,
    )
