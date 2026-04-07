"""
Duplicates router backed by the shared duplicate-detection service.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models.asset import Asset, ExportState
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


class BulkExcludeBody(BaseModel):
    ids: list[str]


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


def _stable_cluster_id(prefix: str, asset_ids: list[str]) -> str:
    """Deterministic cluster ID based on sorted asset IDs — stable across requests."""
    key = prefix + ":" + ":".join(sorted(asset_ids))
    return hashlib.sha256(key.encode()).hexdigest()[:36]


def _build_cluster_response(
    cluster_id: str,
    cluster_type: str,
    cluster_assets: list[Asset],
) -> DuplicateClusterResponse:
    best_id = _representative_id(cluster_assets)
    images = [
        _asset_payload(
            asset,
            keep=str(asset.id) == best_id,
            score=float(asset.composite_score or 0.0),
        )
        for asset in sorted(cluster_assets, key=_quality_tuple, reverse=True)
    ]
    return DuplicateClusterResponse(
        id=cluster_id,
        cluster_type=cluster_type,
        image_count=len(images),
        images=images,
        best_id=best_id,
    )


@router.post(
    "/projects/{project_id}/duplicates/scan",
    status_code=status.HTTP_202_ACCEPTED,
)
async def scan_duplicates(
    project_id: str,
    stages: str | None = Query(
        None,
        description="Comma-separated stages to run: exact,phash,embedding,face. Defaults to all.",
    ),
) -> dict:
    """Queue a background duplicate detection scan. Optionally limit stages."""
    stage_list = [s.strip() for s in stages.split(",")] if stages else None
    job_id = await queue_duplicate_scan(project_id, stages=stage_list)
    return {"job_id": job_id}


@router.post(
    "/projects/{project_id}/duplicates/exclude",
    status_code=status.HTTP_200_OK,
)
async def exclude_duplicate_assets(
    project_id: str,
    body: BulkExcludeBody,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Non-destructive: mark assets as excluded from export.
    Assets remain in the project and can be re-included at any time."""
    if not body.ids:
        raise HTTPException(status_code=400, detail="ids required")

    excluded = 0
    for asset_id in body.ids:
        asset = await db.get(Asset, asset_id)
        if asset and asset.project_id == project_id and not asset.is_rejected:
            asset.export_state = ExportState.EXCLUDED.value
            excluded += 1

    await db.commit()
    logger.info("Excluded %d duplicate assets from project %s", excluded, project_id)
    return {"excluded": excluded}


@router.get("/projects/{project_id}/duplicates", response_model=DuplicateListResponse)
async def get_duplicate_clusters(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> DuplicateListResponse:
    """Returns duplicate clusters for review.

    Exact and pHash clusters are detected on-the-fly from stored hash fields so
    they are always current.  Embedding/face clusters are returned from the
    last background scan (POST /duplicates/scan) if one has been run.
    """
    # Load all non-rejected assets for this project
    asset_result = await db.execute(
        select(Asset).where(
            Asset.project_id == project_id,
            Asset.is_rejected.is_(False),
        )
    )
    assets = asset_result.scalars().all()

    if not assets:
        return DuplicateListResponse(clusters=[], total_clusters=0, total_duplicates=0)

    asset_lookup: dict[str, Asset] = {str(a.id): a for a in assets}
    response_clusters: list[DuplicateClusterResponse] = []
    seen_ids: set[str] = set()

    # ── Stage 1: Exact SHA-256 (on-the-fly) ──────────────────────────────────
    hash_groups: dict[str, list[str]] = {}
    for asset in assets:
        if asset.sha256_hash:
            hash_groups.setdefault(asset.sha256_hash, []).append(str(asset.id))

    for _, group in hash_groups.items():
        if len(group) < 2:
            continue
        cluster_id = _stable_cluster_id("exact", group)
        cluster_assets = [asset_lookup[aid] for aid in group]
        response_clusters.append(_build_cluster_response(cluster_id, "exact", cluster_assets))
        seen_ids.update(group)

    # ── Stage 2: pHash (on-the-fly via Union-Find) ────────────────────────────
    try:
        import imagehash as _imagehash

        threshold = settings.PHASH_THRESHOLD
        unclustered = [a for a in assets if str(a.id) not in seen_ids and a.phash]
        if len(unclustered) >= 2:
            parent: dict[str, str] = {str(a.id): str(a.id) for a in unclustered}

            def _find(x: str) -> str:
                while parent[x] != x:
                    parent[x] = parent[parent[x]]
                    x = parent[x]
                return x

            def _union(x: str, y: str) -> None:
                px, py = _find(x), _find(y)
                if px != py:
                    parent[px] = py

            # O(n²) pairwise comparison — acceptable for typical dataset sizes (< 10k images).
            # For very large projects, run the background scan instead which uses indexed Qdrant search.
            for i, a1 in enumerate(unclustered):
                try:
                    h1 = _imagehash.hex_to_hash(a1.phash)
                except Exception as exc:
                    logger.debug("Failed to parse phash for asset %s: %s", a1.id[:8], exc)
                    continue
                for a2 in unclustered[i + 1 :]:
                    try:
                        h2 = _imagehash.hex_to_hash(a2.phash)
                        if h1 - h2 <= threshold:
                            _union(str(a1.id), str(a2.id))
                    except Exception as exc:
                        logger.debug(
                            "Failed to compare phash for assets %s/%s: %s",
                            a1.id[:8], a2.id[:8], exc
                        )
                        continue

            phash_groups: dict[str, list[str]] = {}
            for a in unclustered:
                root = _find(str(a.id))
                phash_groups.setdefault(root, []).append(str(a.id))

            for _, group in phash_groups.items():
                if len(group) < 2:
                    continue
                cluster_id = _stable_cluster_id("phash", group)
                cluster_assets = [asset_lookup[aid] for aid in group]
                response_clusters.append(_build_cluster_response(cluster_id, "phash", cluster_assets))
                seen_ids.update(group)

    except ImportError:
        logger.debug("imagehash not installed; skipping on-the-fly pHash detection")

    # ── Stage 3+4: Embedding/face clusters from last background scan ──────────
    scan_assets = [
        a for a in assets
        if str(a.id) not in seen_ids
        and a.duplicate_cluster_id
        and a.duplicate_type in ("embedding", "face")
    ]
    scan_clusters_map: dict[str, list[Asset]] = {}
    scan_cluster_types: dict[str, str] = {}
    for asset in scan_assets:
        cid = str(asset.duplicate_cluster_id)
        scan_clusters_map.setdefault(cid, []).append(asset)
        if asset.duplicate_type:
            scan_cluster_types[cid] = asset.duplicate_type

    for cid, cluster_assets in scan_clusters_map.items():
        if len(cluster_assets) < 2:
            continue
        response_clusters.append(
            _build_cluster_response(cid, scan_cluster_types.get(cid, "embedding"), cluster_assets)
        )

    response_clusters.sort(key=lambda c: (c.image_count, c.cluster_type), reverse=True)
    total_duplicates = sum(max(c.image_count - 1, 0) for c in response_clusters)

    return DuplicateListResponse(
        clusters=response_clusters,
        total_clusters=len(response_clusters),
        total_duplicates=total_duplicates,
    )
