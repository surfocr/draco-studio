"""
Augmentation Service — plans and executes dataset augmentation operations.
All augmented assets are non-destructive — originals never modified.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.asset import Asset

logger = logging.getLogger(__name__)


@dataclass
class AugmentationPlan:
    id: str
    operation: str
    reason: str
    gap_addressed: str
    source_asset_id: Optional[str]
    estimated_benefit: float
    params: dict[str, Any]
    priority: int


@dataclass
class AugmentationResult:
    id: str
    source_asset_id: str
    output_path: str
    operation: str
    provider: str
    status: str  # "pending_review" | "approved" | "rejected"
    before_score: Optional[float]
    after_score: Optional[float]
    identity_preserved: Optional[bool]
    created_at: str
    params_used: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class AugmentationJob:
    id: str
    plan_item_id: str
    status: str
    result: Optional[AugmentationResult] = None
    error: Optional[str] = None


# In-memory store for augmentation results (would be DB table in production)
_augmentation_results: dict[str, AugmentationResult] = {}


class AugmentationService:

    async def plan_expansions(
        self,
        project_id: str,
        db: AsyncSession,
        coach_report: Any = None,
    ) -> list[AugmentationPlan]:
        """Analyze dataset gaps and return prioritized augmentation plan."""
        result = await db.execute(
            select(Asset).where(
                Asset.project_id == project_id,
                Asset.is_rejected.is_(False),
            )
        )
        assets = result.scalars().all()
        if not assets:
            return []

        plans: list[AugmentationPlan] = []
        priority = 1

        # Check shot type gaps
        shot_counts: dict[str, int] = {}
        for a in assets:
            st = a.shot_type or "unknown"
            shot_counts[st] = shot_counts.get(st, 0) + 1

        total = len(assets)
        has_wide = shot_counts.get("wide", 0) + shot_counts.get("full_body", 0) > 0
        if not has_wide and total > 0:
            # Find medium shots to use as source
            medium_assets = [a for a in assets if a.shot_type in ("medium", "closeup")]
            if medium_assets:
                source = max(medium_assets, key=lambda a: a.composite_score or 0)
                plans.append(AugmentationPlan(
                    id=str(uuid.uuid4()),
                    operation="outpaint",
                    reason="No wide/full-body shots in dataset",
                    gap_addressed="shot_type_diversity",
                    source_asset_id=source.id,
                    estimated_benefit=0.8,
                    params={"target_width": 768, "target_height": 1024, "prompt": "full body shot"},
                    priority=priority,
                ))
                priority += 1

        # Check aspect ratio coverage
        ratios: set[str] = set()
        for a in assets:
            if a.width and a.height:
                r = round(a.width / a.height, 2)
                if r > 1.2:
                    ratios.add("landscape")
                elif r < 0.8:
                    ratios.add("portrait")
                else:
                    ratios.add("square")

        if "square" not in ratios:
            best = max(assets, key=lambda a: a.composite_score or 0)
            plans.append(AugmentationPlan(
                id=str(uuid.uuid4()),
                operation="crop_to_aspect",
                reason="No square (1:1) images in dataset",
                gap_addressed="aspect_ratio_diversity",
                source_asset_id=best.id,
                estimated_benefit=0.5,
                params={"target_w": 1, "target_h": 1},
                priority=priority,
            ))
            priority += 1

        # Flip augmentation for angle variety
        yaw_assets = [a for a in assets if a.head_pose_yaw is not None]
        if yaw_assets:
            front_only = all(abs(a.head_pose_yaw) < 15 for a in yaw_assets)
            if front_only and len(yaw_assets) >= 5:
                top_assets = sorted(yaw_assets, key=lambda a: a.composite_score or 0, reverse=True)[:3]
                for src in top_assets:
                    plans.append(AugmentationPlan(
                        id=str(uuid.uuid4()),
                        operation="flip_horizontal",
                        reason="All front-facing — flip to add variety",
                        gap_addressed="angle_diversity",
                        source_asset_id=src.id,
                        estimated_benefit=0.4,
                        params={},
                        priority=priority,
                    ))
                    priority += 1

        return sorted(plans, key=lambda p: p.priority)

    async def outpaint_to_ratio(
        self,
        asset_id: str,
        target_width: int,
        target_height: int,
        db: AsyncSession,
        provider_name: str = "auto",
        prompt: str | None = None,
    ) -> AugmentationResult:
        asset = await db.get(Asset, asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")

        provider = await self._resolve_editing_provider(provider_name)

        from providers.base import OutpaintRequest
        request = OutpaintRequest(
            asset_id=asset.filepath,
            target_width=target_width,
            target_height=target_height,
            prompt=prompt,
        )

        edit_result = await provider.outpaint(request)

        result_id = str(uuid.uuid4())
        aug_result = AugmentationResult(
            id=result_id,
            source_asset_id=asset_id,
            output_path=edit_result.output_path,
            operation="outpaint",
            provider=edit_result.provider,
            status="pending_review",
            before_score=asset.composite_score,
            after_score=None,
            identity_preserved=edit_result.identity_preserved,
            created_at=datetime.now(timezone.utc).isoformat(),
            params_used={"target_width": target_width, "target_height": target_height},
            error=edit_result.error if not edit_result.success else None,
        )
        _augmentation_results[result_id] = aug_result
        return aug_result

    async def auto_fit_assets(
        self,
        asset_ids: list[str],
        target_width: int,
        target_height: int,
        db: AsyncSession,
        provider_name: str = "auto",
    ) -> str:
        job_id = str(uuid.uuid4())

        async def _run() -> None:
            for asset_id in asset_ids:
                try:
                    await self.outpaint_to_ratio(
                        asset_id, target_width, target_height, db, provider_name
                    )
                except Exception as e:
                    logger.error(f"auto_fit failed for {asset_id}: {e}")

        from workers.job_queue import get_job_queue
        queue = get_job_queue()
        await queue.submit(_run)
        return job_id

    async def approve_result(self, result_id: str, db: AsyncSession) -> Asset:
        result = _augmentation_results.get(result_id)
        if not result:
            raise ValueError(f"Result {result_id} not found")

        source = await db.get(Asset, result.source_asset_id)
        if not source:
            raise ValueError(f"Source asset {result.source_asset_id} not found")

        from pathlib import Path

        new_asset = Asset(
            id=str(uuid.uuid4()),
            project_id=source.project_id,
            filename=Path(result.output_path).name,
            filepath=result.output_path,
            is_augmented=True,
            augmentation_source_id=result.source_asset_id,
            composite_score=result.after_score or result.before_score,
        )
        db.add(new_asset)
        await db.flush()
        await db.commit()

        result.status = "approved"
        return new_asset

    async def reject_result(self, result_id: str, db: AsyncSession) -> None:
        result = _augmentation_results.get(result_id)
        if result:
            result.status = "rejected"

    async def get_result(self, result_id: str) -> AugmentationResult | None:
        return _augmentation_results.get(result_id)

    async def list_pending_results(self) -> list[AugmentationResult]:
        return [r for r in _augmentation_results.values() if r.status == "pending_review"]

    async def _resolve_editing_provider(self, provider_name: str) -> Any:
        from providers.registry import get_registry

        registry = get_registry()

        if provider_name != "auto":
            provider = registry.get("ai_outpainting", provider_name) or registry.get(
                "ai_image_editor", provider_name
            )
            if provider and await provider.is_available():
                return provider

        # Auto: try ComfyUI first, fall back to basic editor
        comfy = registry.get("ai_outpainting", "comfyui")
        if comfy and await comfy.is_available():
            return comfy

        basic = registry.get("ai_image_editor", "basic_editor")
        if basic:
            return basic

        # Last resort: create basic editor directly
        from providers.editing.basic_editor import BasicImageEditor

        return BasicImageEditor()
