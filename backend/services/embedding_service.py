"""
Embedding indexing service.
Provides on-demand / batch re-indexing of assets into Qdrant via FastEmbedProvider.
Normal ingest already auto-embeds via the analysis pipeline (services/analysis.py Stage 2).
This service is for manual re-indexing, recovery, and coverage reporting.
"""
from __future__ import annotations

import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.asset import Asset

logger = logging.getLogger(__name__)


async def index_asset(asset_id: str, db: AsyncSession) -> bool:
    """Compute and upsert the CLIP embedding for a single asset. Idempotent."""
    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if asset is None:
        logger.warning("index_asset: asset %s not found", asset_id)
        return False

    try:
        from providers.registry import get_registry
        embed_provider = get_registry().get("embedding", "fastembed")
        if embed_provider is None:
            logger.warning("index_asset: embedding provider not registered")
            return False

        embed_result = await embed_provider.embed_image(asset.filepath)
        await embed_provider.upsert_embedding(
            asset_id,
            embed_result.vector,
            payload={"project_id": asset.project_id, "filename": asset.filename},
        )
        logger.debug("Indexed asset %s", asset_id[:8])
        return True
    except Exception as exc:
        logger.error("Failed to index asset %s: %s", asset_id[:8], exc)
        return False


async def index_project(
    project_id: str, db: AsyncSession, force: bool = False
) -> dict:
    """
    Embed all assets in a project that haven't been analyzed yet (or all if force=True).
    Returns {"indexed": int, "failed": int, "total": int}.
    """
    query = select(Asset).where(Asset.project_id == project_id)
    if not force:
        # Only embed assets that have never been through analysis
        query = query.where(Asset.analyzed_at.is_(None))

    result = await db.execute(query)
    assets = result.scalars().all()

    success = 0
    failed = 0
    for asset in assets:
        ok = await index_asset(asset.id, db)
        if ok:
            success += 1
        else:
            failed += 1

    logger.info(
        "index_project %s: %d indexed, %d failed out of %d",
        project_id[:8], success, failed, len(assets),
    )
    return {"indexed": success, "failed": failed, "total": len(assets)}


async def get_embedding_status(project_id: str, db: AsyncSession) -> dict:
    """
    Returns embedding coverage stats for a project.
    DB counts come from analyzed_at; Qdrant count comes from the provider.
    """
    from sqlalchemy import func

    total_r = await db.execute(
        select(func.count()).where(Asset.project_id == project_id)
    )
    total: int = total_r.scalar() or 0

    analyzed_r = await db.execute(
        select(func.count()).where(
            Asset.project_id == project_id,
            Asset.analyzed_at.isnot(None),
        )
    )
    analyzed: int = analyzed_r.scalar() or 0

    qdrant_count = 0
    try:
        from providers.registry import get_registry
        embed_provider = get_registry().get("embedding", "fastembed")
        if embed_provider:
            qdrant_count = await embed_provider.get_collection_count()
    except Exception:
        pass

    return {
        "total_assets": total,
        "analyzed_assets": analyzed,
        "pending_analysis": total - analyzed,
        "qdrant_vectors": qdrant_count,
        "coverage_pct": round(analyzed / total * 100, 1) if total > 0 else 0.0,
    }
