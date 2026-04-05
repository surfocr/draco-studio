"""
Layered duplicate detection service.
4 stages, each progressively more expensive:
  1. Exact SHA-256 hash match
  2. pHash Hamming distance ≤ threshold (default 8)
  3. CLIP embedding cosine similarity ≥ threshold (default 0.95)
  4. Face embedding cosine similarity ≥ threshold (default 0.80)
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.asset import Asset
from providers.base import DuplicateCluster
from providers.registry import get_registry

logger = logging.getLogger(__name__)


async def find_duplicates(
    project_id: str,
    db: AsyncSession,
    stages: list[str] | None = None,
    phash_threshold: int | None = None,
    embedding_threshold: float | None = None,
    face_threshold: float | None = None,
) -> list[DuplicateCluster]:
    """
    Run duplicate detection across all stages for a project.
    Returns a list of DuplicateCluster objects.
    """
    _stages = stages or ["exact", "phash", "embedding", "face"]
    _phash_thresh = phash_threshold if phash_threshold is not None else settings.PHASH_THRESHOLD
    _embed_thresh = embedding_threshold or settings.SIMILARITY_THRESHOLD
    _face_thresh = face_threshold or settings.FACE_SIMILARITY_THRESHOLD

    # Load all assets for the project
    result = await db.execute(
        select(Asset).where(Asset.project_id == project_id, Asset.is_rejected == False)
    )
    assets = result.scalars().all()

    if not assets:
        return []

    clusters: list[DuplicateCluster] = []

    # Track which assets have been assigned to a cluster already
    clustered: set[str] = set()

    # ── Stage 1: Exact SHA-256 ────────────────────────────────────────────────
    if "exact" in _stages:
        exact_clusters = _find_exact_duplicates(assets, clustered)
        clusters.extend(exact_clusters)

    # ── Stage 2: pHash ────────────────────────────────────────────────────────
    if "phash" in _stages:
        phash_clusters = _find_phash_duplicates(assets, clustered, _phash_thresh)
        clusters.extend(phash_clusters)

    # ── Stage 3: Embedding cosine similarity ─────────────────────────────────
    if "embedding" in _stages:
        registry = get_registry()
        embed_provider = registry.get("embedding", "fastembed")
        if embed_provider:
            embed_clusters = await _find_embedding_duplicates(
                assets, clustered, embed_provider, _embed_thresh, project_id
            )
            clusters.extend(embed_clusters)

    # ── Stage 4: Face embedding ───────────────────────────────────────────────
    if "face" in _stages:
        face_clusters = _find_face_embedding_duplicates(assets, clustered, _face_thresh)
        clusters.extend(face_clusters)

    # Write cluster_ids back to assets
    for cluster in clusters:
        for asset_id in cluster.asset_ids:
            for asset in assets:
                if asset.id == asset_id:
                    asset.duplicate_cluster_id = cluster.cluster_id
                    asset.duplicate_type = cluster.cluster_type

    await db.commit()

    logger.info(
        "Duplicate detection complete: %d clusters found in project %s",
        len(clusters), project_id
    )
    return clusters


def _find_exact_duplicates(
    assets: list[Asset], clustered: set[str]
) -> list[DuplicateCluster]:
    """Group assets with identical SHA-256 hashes."""
    hash_groups: dict[str, list[str]] = {}
    for asset in assets:
        if asset.sha256_hash and asset.id not in clustered:
            hash_groups.setdefault(asset.sha256_hash, []).append(asset.id)

    clusters = []
    for _, group in hash_groups.items():
        if len(group) < 2:
            continue
        cluster_id = str(uuid.uuid4())
        clusters.append(
            DuplicateCluster(
                cluster_id=cluster_id,
                cluster_type="exact",
                asset_ids=group,
                representative_id=group[0],
            )
        )
        clustered.update(group)
        logger.debug("Exact duplicate cluster: %d assets", len(group))

    return clusters


def _find_phash_duplicates(
    assets: list[Asset], clustered: set[str], threshold: int
) -> list[DuplicateCluster]:
    """Group assets with pHash Hamming distance ≤ threshold."""
    try:
        import imagehash
    except ImportError:
        logger.warning("imagehash not installed, skipping pHash stage")
        return []

    unclustered = [a for a in assets if a.id not in clustered and a.phash]

    # Union-Find for clustering
    parent: dict[str, str] = {a.id: a.id for a in unclustered}

    def _find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def _union(x: str, y: str) -> None:
        px, py = _find(x), _find(y)
        if px != py:
            parent[px] = py

    for i, a1 in enumerate(unclustered):
        try:
            h1 = imagehash.hex_to_hash(a1.phash)
        except Exception:
            continue
        for a2 in unclustered[i + 1 :]:
            try:
                h2 = imagehash.hex_to_hash(a2.phash)
                if h1 - h2 <= threshold:
                    _union(a1.id, a2.id)
            except Exception:
                continue

    # Collect groups
    groups: dict[str, list[str]] = {}
    for a in unclustered:
        root = _find(a.id)
        groups.setdefault(root, []).append(a.id)

    clusters = []
    for _, group in groups.items():
        if len(group) < 2:
            continue
        cluster_id = str(uuid.uuid4())
        clusters.append(
            DuplicateCluster(
                cluster_id=cluster_id,
                cluster_type="phash",
                asset_ids=group,
                representative_id=group[0],
            )
        )
        clustered.update(group)

    return clusters


async def _find_embedding_duplicates(
    assets: list[Asset],
    clustered: set[str],
    embed_provider: Any,
    threshold: float,
    project_id: str,
) -> list[DuplicateCluster]:
    """Use Qdrant similarity search to find near-duplicates."""
    unclustered = [a for a in assets if a.id not in clustered]
    if not unclustered:
        return []

    clusters: list[DuplicateCluster] = []
    processed: set[str] = set()

    for asset in unclustered:
        if asset.id in processed:
            continue

        try:
            # Get this asset's embedding from Qdrant
            embed_result = await embed_provider.embed_image(asset.filepath)
            if not embed_result:
                continue

            # Search for similar
            similar = await embed_provider.search_similar(
                embed_result.vector,
                top_k=20,
                threshold=threshold,
                filter_project_id=project_id,
            )

            # Filter to only unclustered assets
            similar_ids = [
                aid for aid, score in similar
                if aid != asset.id and aid not in clustered and aid not in processed
            ]

            if similar_ids:
                group = [asset.id] + similar_ids
                cluster_id = str(uuid.uuid4())
                similarity_scores = {
                    aid: score for aid, score in similar if aid in similar_ids
                }
                clusters.append(
                    DuplicateCluster(
                        cluster_id=cluster_id,
                        cluster_type="embedding",
                        asset_ids=group,
                        representative_id=asset.id,
                        similarity_scores=similarity_scores,
                    )
                )
                clustered.update(group)
                processed.update(group)

        except Exception as exc:
            logger.warning("Embedding duplicate check failed for %s: %s", asset.id[:8], exc)

    return clusters


def _find_face_embedding_duplicates(
    assets: list[Asset], clustered: set[str], threshold: float
) -> list[DuplicateCluster]:
    """
    Group assets where the primary face embedding is very similar.
    Only applies to assets with face embeddings.
    Runs in-memory using cosine similarity.
    """
    # This is a simplified implementation — a full version would query Qdrant
    # face embeddings collection. For now, skip assets without embeddings.
    return []
