"""
Task definitions — submit analysis and caption jobs to the queue.
"""
from __future__ import annotations

import logging

from database import AsyncSessionLocal
from services.caption import CaptionService
from workers.job_queue import get_job_queue

logger = logging.getLogger(__name__)


async def queue_analysis_task(asset_id: str) -> str:
    """Queue full analysis for a single asset. Returns job_id."""
    from services.analysis import analyze_asset

    queue = get_job_queue()

    async def _run() -> dict:
        async with AsyncSessionLocal() as db:
            asset = await analyze_asset(asset_id, db)
            await db.commit()
            return {"asset_id": asset_id, "ok": asset is not None}

    return await queue.submit(_run, job_type="analysis")


async def queue_caption_task(
    asset_ids: list[str],
    provider_name: str,
    style: str,
    options: dict | None = None,
) -> str:
    """Queue bulk caption generation. Returns job_id."""
    from services.caption import generate_caption

    queue = get_job_queue()

    async def _run() -> dict:
        results = {"success": 0, "failed": 0, "errors": []}
        async with AsyncSessionLocal() as db:
            for i, asset_id in enumerate(asset_ids):
                try:
                    version = await generate_caption(
                        asset_id, provider_name, style, db, options
                    )
                    if version:
                        results["success"] += 1
                    else:
                        results["failed"] += 1
                except Exception as exc:
                    results["failed"] += 1
                    results["errors"].append(str(exc))
            await db.commit()
        return results

    return await queue.submit(_run, job_type="caption")


async def queue_duplicate_scan(project_id: str) -> str:
    """Queue duplicate detection scan for a project."""
    from services.duplicate import find_duplicates

    queue = get_job_queue()

    async def _run() -> dict:
        async with AsyncSessionLocal() as db:
            clusters = await find_duplicates(project_id, db)
            return {"clusters_found": len(clusters)}

    return await queue.submit(_run, job_type="duplicate_scan")


async def queue_ai_judge_task(
    asset_ids: list[str],
    provider_name: str = "auto",
    job_id: str | None = None,
) -> str:
    """Queue AI judge scoring for a batch of assets. Returns job_id."""
    from services.ai_judge import get_ai_judge
    from sqlalchemy import select
    from models.asset import Asset

    queue = get_job_queue()

    async def _run() -> dict:
        results = {"scored": 0, "failed": 0, "errors": []}
        async with AsyncSessionLocal() as db:
            for asset_id in asset_ids:
                try:
                    result = await db.execute(
                        select(Asset).where(Asset.id == asset_id)
                    )
                    asset = result.scalar_one_or_none()
                    if asset is None:
                        results["failed"] += 1
                        results["errors"].append(f"{asset_id}: not found")
                        continue
                    judge = get_ai_judge(
                        provider_name,
                        project_id=asset.project_id,
                        task_key="ranking_explanation",
                    )
                    await judge.score_image(asset.filepath, asset_id, db=db)
                    results["scored"] += 1
                except Exception as exc:
                    results["failed"] += 1
                    results["errors"].append(f"{asset_id}: {exc}")
        return results

    return await queue.submit(_run, job_type="ai_judge", job_id=job_id)


async def queue_export_sidecars_task(
    project_id: str,
    asset_ids: list[str],
    output_dir: str | None,
    job_id: str | None = None,
) -> str:
    """Queue sidecar .txt file export for a set of assets. Returns job_id."""
    queue = get_job_queue()
    service = CaptionService()

    async def _run() -> dict:
        written = 0
        errors: list[str] = []
        async with AsyncSessionLocal() as db:
            for asset_id in asset_ids:
                try:
                    path = await service.write_sidecar_direct(asset_id, db, output_dir)
                    if path:
                        written += 1
                    else:
                        errors.append(f"{asset_id}: no active caption")
                except Exception as exc:
                    errors.append(f"{asset_id}: {exc}")
        return {"written": written, "errors": errors, "job_id": job_id}

    return await queue.submit(_run, job_type="export_sidecars", job_id=job_id)
