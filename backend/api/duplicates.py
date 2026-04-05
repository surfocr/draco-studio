"""
Duplicates router — pHash-based duplicate cluster detection for a project.
"""
from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models.asset import Asset

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["duplicates"])


@router.get("/projects/{project_id}/duplicates")
async def get_duplicate_clusters(
    project_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
    min_similarity: float = Query(default=0.85, ge=0.0, le=1.0),
):
    """
    Return duplicate clusters for a project, grouped by pHash proximity.
    Exact duplicates (same sha256) are reported first with similarity=1.0.
    Near-duplicates are grouped by Hamming distance on perceptual hash.
    """
    result = await db.execute(
        select(Asset).where(
            Asset.project_id == project_id,
            Asset.is_rejected.is_(False),
        )
    )
    assets = result.scalars().all()

    clusters: list[dict] = []
    processed: set[str] = set()

    # ── Exact duplicates (sha256) ────────────────────────────────────────────
    sha_map: dict[str, list[Asset]] = {}
    for asset in assets:
        if asset.sha256_hash:
            sha_map.setdefault(asset.sha256_hash, []).append(asset)

    for sha, group in sha_map.items():
        if len(group) < 2:
            continue
        for a in group:
            processed.add(str(a.id))
        clusters.append({
            "id": f"{group[0].id}_exact",
            "type": "exact",
            "similarity": 1.0,
            "assets": [_asset_dict(a) for a in group],
        })

    # ── Near-duplicates (pHash Hamming distance) ─────────────────────────────
    phash_assets = [a for a in assets if a.phash and str(a.id) not in processed]

    for i, asset_a in enumerate(phash_assets):
        if str(asset_a.id) in processed:
            continue

        cluster_members = [asset_a]
        best_similarity = min_similarity

        for asset_b in phash_assets[i + 1:]:
            if str(asset_b.id) in processed:
                continue
            try:
                import imagehash
                hash_a = imagehash.hex_to_hash(asset_a.phash)
                hash_b = imagehash.hex_to_hash(asset_b.phash)
                diff = hash_a - hash_b
                similarity = 1.0 - (diff / 64.0)
                if similarity >= min_similarity:
                    cluster_members.append(asset_b)
                    best_similarity = max(best_similarity, similarity)
            except Exception:
                continue

        if len(cluster_members) > 1:
            for m in cluster_members:
                processed.add(str(m.id))
            clusters.append({
                "id": f"{asset_a.id}_near",
                "type": "near",
                "similarity": round(best_similarity, 4),
                "assets": [_asset_dict(a) for a in cluster_members],
            })

    return {"clusters": clusters, "total": len(clusters)}


def _asset_dict(asset: Asset) -> dict:
    return {
        "id": str(asset.id),
        "filename": asset.filename,
        "thumbnail_url": f"/api/assets/{asset.id}/thumbnail",
        "composite_score": asset.composite_score,
        "face_count": asset.face_count,
        "width": asset.width,
        "height": asset.height,
    }
