"""
Centralized asset review-state transitions and non-destructive deletion.
"""
from __future__ import annotations

import logging

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models.asset import Asset, ReviewState
from models.project import Project
from providers.registry import get_registry

logger = logging.getLogger(__name__)


class AssetStateService:
    """Owns review-state transitions, delete cleanup, and project stat sync."""

    REVIEWED_STATES = {
        ReviewState.APPROVED.value,
        ReviewState.REJECTED.value,
    }

    @classmethod
    async def sync_project_counters(
        cls,
        project_id: str,
        db: AsyncSession,
    ) -> dict[str, int]:
        """Recompute denormalized project counters from live asset rows."""
        project = await db.get(Project, project_id)
        if project is None:
            raise LookupError(f"Project {project_id} not found")

        await db.flush()

        stmt = select(
            func.count(Asset.id).label("asset_count"),
            func.coalesce(
                func.sum(
                    case((Asset.review_state.in_(tuple(cls.REVIEWED_STATES)), 1), else_=0)
                ),
                0,
            ).label("reviewed_count"),
            func.coalesce(
                func.sum(case((Asset.is_flagged.is_(True), 1), else_=0)),
                0,
            ).label("flagged_count"),
            func.coalesce(
                func.sum(case((Asset.is_rejected.is_(True), 1), else_=0)),
                0,
            ).label("rejected_count"),
        ).where(Asset.project_id == project_id)

        counts = (await db.execute(stmt)).one()
        project.asset_count = int(counts.asset_count or 0)
        project.reviewed_count = int(counts.reviewed_count or 0)
        project.flagged_count = int(counts.flagged_count or 0)
        project.rejected_count = int(counts.rejected_count or 0)
        await db.flush()

        return {
            "asset_count": project.asset_count,
            "reviewed_count": project.reviewed_count,
            "flagged_count": project.flagged_count,
            "rejected_count": project.rejected_count,
        }

    @classmethod
    async def apply_review_update(
        cls,
        asset: Asset,
        *,
        db: AsyncSession,
        review_state: str | None = None,
        is_flagged: bool | None = None,
        is_rejected: bool | None = None,
        rejection_reason: str | None = None,
    ) -> Asset:
        """Apply a moderation update and normalize obviously conflicting state."""
        if review_state is not None:
            valid_states = {state.value for state in ReviewState}
            if review_state not in valid_states:
                raise ValueError(f"Invalid review_state: {review_state}")
            asset.review_state = review_state

        if is_flagged is not None:
            asset.is_flagged = is_flagged

        if is_rejected is not None:
            asset.is_rejected = is_rejected

        if rejection_reason is not None:
            asset.rejection_reason = rejection_reason

        if asset.review_state == ReviewState.APPROVED.value:
            asset.is_rejected = False
            if rejection_reason is None:
                asset.rejection_reason = None
        elif asset.review_state == ReviewState.REJECTED.value:
            asset.is_rejected = True

        await db.flush()
        return asset

    @classmethod
    async def approve_asset(cls, asset: Asset, db: AsyncSession) -> Asset:
        return await cls.apply_review_update(
            asset,
            db=db,
            review_state=ReviewState.APPROVED.value,
            is_rejected=False,
            rejection_reason=None,
        )

    @classmethod
    async def reject_asset(
        cls,
        asset: Asset,
        db: AsyncSession,
        rejection_reason: str | None = None,
    ) -> Asset:
        return await cls.apply_review_update(
            asset,
            db=db,
            review_state=ReviewState.REJECTED.value,
            is_rejected=True,
            rejection_reason=rejection_reason,
        )

    @classmethod
    async def flag_asset(cls, asset: Asset, db: AsyncSession) -> Asset:
        return await cls.apply_review_update(asset, db=db, is_flagged=True)

    @classmethod
    async def unflag_asset(cls, asset: Asset, db: AsyncSession) -> Asset:
        return await cls.apply_review_update(asset, db=db, is_flagged=False)

    @classmethod
    async def delete_asset(
        cls,
        asset: Asset,
        db: AsyncSession,
        *,
        delete_file: bool = True,
    ) -> None:
        """Delete the DB row after best-effort embedding and trash cleanup."""
        await cls._cleanup_embedding(asset.id)

        if delete_file and asset.filepath:
            registry = get_registry()
            storage = registry.get("storage", "local")
            if storage:
                try:
                    await storage.delete_asset(asset.filepath, asset.id)
                except Exception as exc:
                    logger.warning("Failed to move asset %s to trash: %s", asset.id[:8], exc)

        await db.delete(asset)
        await db.flush()

    @staticmethod
    async def _cleanup_embedding(asset_id: str) -> None:
        registry = get_registry()
        embed_provider = registry.get("embedding", "fastembed")
        if not embed_provider or not hasattr(embed_provider, "delete_embedding"):
            return
        try:
            await embed_provider.delete_embedding(asset_id)
        except Exception as exc:
            logger.warning("Failed to clean embedding for asset %s: %s", asset_id[:8], exc)
