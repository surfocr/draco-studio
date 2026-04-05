"""
Analysis orchestration service.
Runs all analysis stages on an asset in order.
Handles partial failures gracefully.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.asset import Asset
from providers.registry import get_registry

logger = logging.getLogger(__name__)


async def analyze_asset(
    asset_id: str,
    db: AsyncSession,
    progress_callback: Callable[[str, float], None] | None = None,
) -> Asset | None:
    """
    Run the full analysis pipeline on a single asset.
    Updates the Asset record in place.
    Returns the updated Asset, or None if not found.
    """
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if asset is None:
        logger.warning("analyze_asset: asset %s not found", asset_id)
        return None

    def _progress(stage: str, pct: float) -> None:
        if progress_callback:
            progress_callback(stage, pct)
        logger.debug("Analysis %s: %s %.0f%%", asset_id[:8], stage, pct)

    registry = get_registry()
    image_path = asset.filepath

    # ── Stage 1: Face detection ───────────────────────────────────────────────
    _progress("face_detection", 10.0)
    face_results = None
    try:
        face_provider = registry.get("face_detection", "insightface")
        if face_provider and await face_provider.is_available():
            face_results = await face_provider.detect_faces(image_path)
            if face_results:
                asset.face_count = face_results.face_count
                pf = face_results.primary_face
                if pf:
                    asset.primary_face_bbox = pf.bbox.to_dict()
                    asset.landmark_confidence = pf.quality_score
                    asset.head_pose_yaw = pf.pose_yaw
                    asset.head_pose_pitch = pf.pose_pitch
                    asset.head_pose_roll = pf.pose_roll
                    asset.age_estimate = pf.age
                    asset.gender_estimate = pf.gender
                    asset.dominant_emotion = pf.emotion
                    if pf.embedding:
                        asset.face_embedding_id = asset.id  # placeholder
    except Exception as exc:
        logger.warning("Face detection failed for %s: %s", asset_id[:8], exc)

    # ── Stage 2: Image embedding ──────────────────────────────────────────────
    _progress("embedding", 30.0)
    try:
        embed_provider = registry.get("embedding", "fastembed")
        if embed_provider and await embed_provider.is_available():
            embed_result = await embed_provider.embed_image(image_path)
            if embed_result:
                await embed_provider.upsert_embedding(
                    asset_id,
                    embed_result.vector,
                    payload={"project_id": asset.project_id},
                )
    except Exception as exc:
        logger.warning("Embedding failed for %s: %s", asset_id[:8], exc)

    # ── Stage 3: Quality scoring ──────────────────────────────────────────────
    _progress("quality", 60.0)
    try:
        quality_scorer = registry.get("quality", "composite")
        if quality_scorer and await quality_scorer.is_available():
            quality_result = await quality_scorer.score_image(image_path, face_results)
            if quality_result:
                asset.technical_quality = quality_result.technical_quality
                asset.aesthetic_score = quality_result.aesthetic
                asset.face_quality = quality_result.face_quality
                asset.training_usefulness = quality_result.training_usefulness
                asset.composite_score = quality_result.composite_score
                asset.score_breakdown = quality_result.breakdown
    except Exception as exc:
        logger.warning("Quality scoring failed for %s: %s", asset_id[:8], exc)

    # ── Stage 4: Duplicate detection (hash-based, fast) ───────────────────────
    _progress("duplicate_check", 80.0)
    try:
        await _check_phash_duplicates(asset, db)
    except Exception as exc:
        logger.warning("Duplicate check failed for %s: %s", asset_id[:8], exc)

    # ── Finalize ──────────────────────────────────────────────────────────────
    asset.analyzed_at = datetime.now(timezone.utc)
    await db.flush()

    _progress("done", 100.0)
    logger.info("Analysis complete for asset %s", asset_id[:8])
    return asset


async def _check_phash_duplicates(asset: Asset, db: AsyncSession) -> None:
    """
    Stage 2 duplicate check: pHash Hamming distance.
    Marks duplicates found by hash comparison.
    """
    if not asset.phash:
        return

    from sqlalchemy import select, and_
    from models.asset import Asset as A
    from config import settings

    result = await db.execute(
        select(A).where(
            A.project_id == asset.project_id,
            A.id != asset.id,
            A.phash.isnot(None),
        )
    )
    candidates = result.scalars().all()

    for candidate in candidates:
        try:
            import imagehash
            h1 = imagehash.hex_to_hash(asset.phash)
            h2 = imagehash.hex_to_hash(candidate.phash)
            distance = h1 - h2
            if distance <= settings.PHASH_THRESHOLD:
                # Mark both as duplicates
                cluster_id = asset.duplicate_cluster_id or candidate.duplicate_cluster_id
                if not cluster_id:
                    import uuid
                    cluster_id = str(uuid.uuid4())
                asset.duplicate_cluster_id = cluster_id
                asset.duplicate_type = "phash"
                candidate.duplicate_cluster_id = cluster_id
                if not candidate.duplicate_type:
                    candidate.duplicate_type = "phash"
                logger.debug(
                    "pHash duplicate: %s ↔ %s (distance=%d)",
                    asset.id[:8], candidate.id[:8], distance,
                )
                break  # One duplicate is enough to flag it
        except Exception:
            continue


async def analyze_batch(
    asset_ids: list[str],
    db: AsyncSession,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> dict[str, bool]:
    """
    Analyze multiple assets. Returns {asset_id: success}.
    """
    results: dict[str, bool] = {}
    total = len(asset_ids)

    for i, asset_id in enumerate(asset_ids):
        if progress_callback:
            progress_callback(asset_id, i, total)
        try:
            asset = await analyze_asset(asset_id, db)
            results[asset_id] = asset is not None
        except Exception as exc:
            logger.error("Batch analysis failed for %s: %s", asset_id[:8], exc)
            results[asset_id] = False

    await db.commit()
    return results
