"""
Augmentation Service — plans and executes dataset augmentation operations.
All augmented assets are non-destructive — originals never modified.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models.asset import Asset
from models.augmentation import AugmentationJob as AugmentationJobModel
from services.asset_state import AssetStateService

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
    ) -> AugmentationJobModel:
        asset = await db.get(Asset, asset_id)
        if not asset:
            raise ValueError(f"Asset {asset_id} not found")

        provider = await self._resolve_editing_provider(provider_name)

        job = AugmentationJobModel(
            id=str(uuid.uuid4()),
            project_id=asset.project_id,
            source_asset_id=asset_id,
            augmentation_type="outpaint",
            provider=provider_name,
            parameters={"target_width": target_width, "target_height": target_height, "prompt": prompt},
            status="running",
            before_score=asset.composite_score,
            started_at=datetime.now(timezone.utc),
        )
        db.add(job)
        await db.flush()

        try:
            from providers.base import OutpaintRequest
            request = OutpaintRequest(
                asset_id=asset.filepath,
                target_width=target_width,
                target_height=target_height,
                prompt=prompt,
            )
            edit_result = await provider.outpaint(request)
            job.output_path = edit_result.output_path
            job.identity_preserved = edit_result.identity_preserved
            job.status = "pending_review" if edit_result.success else "failed"
            job.error_message = edit_result.error if not edit_result.success else None
        except Exception as exc:
            job.status = "failed"
            job.error_message = str(exc)
        finally:
            job.finished_at = datetime.now(timezone.utc)

        await db.commit()
        return job

    async def auto_fit_assets(
        self,
        asset_ids: list[str],
        target_width: int,
        target_height: int,
        project_id: str,
        provider_name: str = "auto",
        prompt: str | None = None,
    ) -> str:
        _asset_ids = list(asset_ids)
        _target_w = target_width
        _target_h = target_height
        _project_id = project_id
        _provider = provider_name
        _prompt = prompt

        async def _run() -> None:
            from database import AsyncSessionLocal
            async with AsyncSessionLocal() as worker_db:
                resolved_asset_ids = await self._resolve_auto_fit_asset_ids(
                    project_id=_project_id,
                    asset_ids=_asset_ids,
                    db=worker_db,
                )
                for asset_id in resolved_asset_ids:
                    try:
                        await self.outpaint_to_ratio(
                            asset_id, _target_w, _target_h, worker_db, _provider, _prompt
                        )
                    except Exception as e:
                        logger.error("auto_fit failed for %s: %s", asset_id, e)

        from workers.job_queue import get_job_queue
        queue = get_job_queue()
        job_id = await queue.submit(_run, job_type="augmentation")
        return job_id

    async def resolve_auto_fit_asset_count(
        self,
        project_id: str,
        asset_ids: list[str],
        db: AsyncSession,
    ) -> int:
        return len(
            await self._resolve_auto_fit_asset_ids(
                project_id=project_id,
                asset_ids=asset_ids,
                db=db,
            )
        )

    async def approve_result(self, result_id: str, db: AsyncSession) -> Asset:
        job = await db.get(AugmentationJobModel, result_id)
        if not job or job.status not in ("pending_review", "done"):
            raise ValueError(f"Result {result_id} not found or not reviewable")
        if not job.output_path:
            raise ValueError(f"Result {result_id} has no output path")

        source = await db.get(Asset, job.source_asset_id)
        if not source:
            raise ValueError(f"Source asset {job.source_asset_id} not found")
        output_path = Path(job.output_path)
        if not output_path.exists():
            raise ValueError(f"Output file for result {result_id} not found")

        from providers.registry import get_registry

        new_asset = Asset(
            id=str(uuid.uuid4()),
            project_id=source.project_id,
            filename=output_path.name,
            filepath=job.output_path,
            is_augmented=True,
            augmentation_source_id=job.source_asset_id,
            composite_score=job.after_score or job.before_score,
        )
        new_asset.review_state = source.review_state
        new_asset.is_flagged = source.is_flagged
        new_asset.is_rejected = False

        storage = get_registry().get("storage", "local")
        if storage:
            try:
                info = await storage.inspect_image(job.output_path)
                new_asset.width = info.get("width")
                new_asset.height = info.get("height")
                new_asset.mime_type = info.get("mime_type")
                if new_asset.width and new_asset.height:
                    new_asset.file_size = output_path.stat().st_size
                if hasattr(storage, "compute_hashes_from_path"):
                    hashes = await storage.compute_hashes_from_path(job.output_path)
                    new_asset.sha256_hash = hashes.get("sha256")
                    new_asset.phash = hashes.get("phash")
                    new_asset.dhash = hashes.get("dhash")
                    new_asset.ahash = hashes.get("ahash")
                if hasattr(storage, "save_thumbnail"):
                    try:
                        new_asset.thumbnail_small_path = await storage.save_thumbnail(
                            job.output_path, new_asset.id, 128
                        )
                        new_asset.thumbnail_path = await storage.save_thumbnail(
                            job.output_path, new_asset.id, 512
                        )
                    except Exception as exc:
                        logger.warning("Failed to generate thumbnails for augmentation result %s: %s", result_id, exc)
            except Exception as exc:
                logger.warning("Failed to inspect augmentation result %s: %s", result_id, exc)
        db.add(new_asset)
        job.status = "approved"
        await db.flush()
        await AssetStateService.sync_project_counters(source.project_id, db)
        await db.commit()
        return new_asset

    async def reject_result(self, result_id: str, db: AsyncSession) -> None:
        job = await db.get(AugmentationJobModel, result_id)
        if job:
            job.status = "rejected"
            await db.commit()

    async def get_result(self, result_id: str, db: AsyncSession) -> AugmentationJobModel | None:
        return await db.get(AugmentationJobModel, result_id)

    async def list_pending_results(
        self,
        db: AsyncSession,
        *,
        project_id: str | None = None,
    ) -> list[AugmentationJobModel]:
        stmt = select(AugmentationJobModel).where(
            AugmentationJobModel.status == "pending_review"
        )
        if project_id:
            stmt = stmt.where(AugmentationJobModel.project_id == project_id)
        result = await db.execute(stmt.order_by(AugmentationJobModel.created_at.desc()))
        return list(result.scalars().all())

    async def _resolve_auto_fit_asset_ids(
        self,
        *,
        project_id: str,
        asset_ids: list[str],
        db: AsyncSession,
    ) -> list[str]:
        if asset_ids:
            result = await db.execute(
                select(Asset.id).where(
                    Asset.project_id == project_id,
                    Asset.id.in_(asset_ids),
                    Asset.is_rejected.is_(False),
                )
            )
            return [row[0] for row in result.all()]

        result = await db.execute(
            select(Asset.id).where(
                Asset.project_id == project_id,
                Asset.is_rejected.is_(False),
            )
        )
        return [row[0] for row in result.all()]

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

        raise ValueError(
            "No outpainting provider available — ComfyUI required for outpaint operations. "
            "BasicImageEditor does not support outpainting."
        )
