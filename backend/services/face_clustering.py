"""
Face clustering service.
Loads face embeddings from Qdrant, runs agglomerative clustering,
and creates IdentityCluster records.
"""
from __future__ import annotations

import logging
import uuid
from collections import defaultdict

import numpy as np
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.asset import Asset
from models.face import IdentityCluster
from services.asset_quality import pick_best_asset

logger = logging.getLogger(__name__)

DISTANCE_THRESHOLD = 0.6  # Cosine distance threshold for same-identity


async def run_face_clustering(project_id: str, db: AsyncSession) -> dict:
    """
    Cluster face embeddings for a project and create identity clusters.

    1. Fetch all face embeddings from Qdrant face collection
    2. Run agglomerative clustering (cosine distance, average linkage)
    3. Create IdentityCluster records
    4. Assign identity_cluster_id on assets

    Returns summary dict with cluster count and asset count.
    """
    from providers.registry import get_registry

    registry = get_registry()
    embed_provider = registry.get("embedding", "fastembed")

    if not embed_provider or not hasattr(embed_provider, "_qdrant") or embed_provider._qdrant is None:
        return {"error": "Qdrant not available", "clustered": 0, "clusters": 0}

    client = embed_provider._qdrant
    collection = settings.QDRANT_FACE_COLLECTION

    # Check collection exists
    import asyncio
    loop = asyncio.get_event_loop()

    def _collection_exists() -> bool:
        existing = [c.name for c in client.get_collections().collections]
        return collection in existing

    if not await loop.run_in_executor(None, _collection_exists):
        return {"error": "No face embeddings found", "clustered": 0, "clusters": 0}

    # Fetch all face embeddings for this project
    from qdrant_client.models import Filter, FieldCondition, MatchValue

    def _scroll_all() -> list[dict]:
        results = []
        offset = None
        while True:
            points, next_offset = client.scroll(
                collection_name=collection,
                scroll_filter=Filter(
                    must=[FieldCondition(key="project_id", match=MatchValue(value=project_id))]
                ),
                limit=256,
                offset=offset,
                with_payload=True,
                with_vectors=True,
            )
            for p in points:
                results.append({
                    "point_id": p.id,
                    "asset_id": p.payload.get("asset_id"),
                    "face_index": p.payload.get("face_index", 0),
                    "vector": p.vector,
                })
            if next_offset is None or len(points) == 0:
                break
            offset = next_offset
        return results

    face_data = await loop.run_in_executor(None, _scroll_all)

    if len(face_data) < 2:
        return {"error": "Need at least 2 face embeddings to cluster", "clustered": len(face_data), "clusters": 0}

    # Build embedding matrix
    vectors = np.array([f["vector"] for f in face_data], dtype=np.float32)
    asset_ids = [f["asset_id"] for f in face_data]

    # Normalize for cosine distance
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1
    vectors_normed = vectors / norms

    # Agglomerative clustering
    try:
        from sklearn.cluster import AgglomerativeClustering
    except ImportError:
        # Fallback: simple threshold-based clustering
        labels = _simple_clustering(vectors_normed, DISTANCE_THRESHOLD)
    else:
        clustering = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=DISTANCE_THRESHOLD,
            metric="cosine",
            linkage="average",
        )
        labels = clustering.fit_predict(vectors_normed)

    # Group faces by cluster label
    cluster_map: dict[int, list[str]] = defaultdict(list)
    for label, aid in zip(labels, asset_ids):
        cluster_map[int(label)].append(aid)

    # Deduplicate: each asset appears in only one cluster (the one with its primary face)
    asset_to_cluster: dict[str, int] = {}
    for label, aids in cluster_map.items():
        for aid in aids:
            if aid not in asset_to_cluster:
                asset_to_cluster[aid] = label

    # Clear existing clusters for this project
    existing_clusters = await db.execute(
        select(IdentityCluster).where(IdentityCluster.project_id == project_id)
    )
    for old_cluster in existing_clusters.scalars().all():
        await db.delete(old_cluster)

    # Reset identity_cluster_id on all assets
    await db.execute(
        update(Asset)
        .where(Asset.project_id == project_id)
        .values(identity_cluster_id=None)
    )

    # Create new clusters
    cluster_label_to_id: dict[int, str] = {}
    clusters_created = 0

    # Rebuild from deduplicated asset_to_cluster
    final_clusters: dict[int, list[str]] = defaultdict(list)
    for aid, label in asset_to_cluster.items():
        final_clusters[label].append(aid)

    asset_result = await db.execute(
        select(Asset).where(Asset.id.in_(list(asset_to_cluster.keys())))
    )
    asset_lookup = {asset.id: asset for asset in asset_result.scalars().all()}

    for label, aids in sorted(final_clusters.items(), key=lambda x: -len(x[1])):
        unique_aids = list(dict.fromkeys(aids))  # preserve order, deduplicate
        cluster_id = str(uuid.uuid4())
        clusters_created += 1

        rep_asset_id = pick_best_asset(unique_aids, asset_lookup)

        identity = IdentityCluster(
            id=cluster_id,
            project_id=project_id,
            label=f"Person {clusters_created}",
            asset_count=len(unique_aids),
            thumbnail_asset_id=rep_asset_id,
        )
        db.add(identity)
        cluster_label_to_id[label] = cluster_id

        # Assign assets
        for aid in unique_aids:
            await db.execute(
                update(Asset)
                .where(Asset.id == aid)
                .values(identity_cluster_id=cluster_id)
            )

    await db.commit()

    logger.info(
        "Face clustering for project %s: %d clusters from %d faces (%d assets)",
        project_id[:8], clusters_created, len(face_data), len(asset_to_cluster),
    )

    return {
        "clustered": len(asset_to_cluster),
        "clusters": clusters_created,
        "project_id": project_id,
    }


def _simple_clustering(vectors: np.ndarray, threshold: float) -> list[int]:
    """Fallback greedy clustering when sklearn is not available."""
    n = len(vectors)
    labels = [-1] * n
    current_label = 0

    for i in range(n):
        if labels[i] != -1:
            continue
        labels[i] = current_label
        for j in range(i + 1, n):
            if labels[j] != -1:
                continue
            # Cosine distance = 1 - cosine_similarity
            sim = float(np.dot(vectors[i], vectors[j]))
            if (1 - sim) < threshold:
                labels[j] = current_label
        current_label += 1

    return labels
