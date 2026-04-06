"""
Task definitions — submit analysis and caption jobs to the queue.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def queue_analysis_task(asset_id: str) -> str:
    """Queue full analysis for a single asset. Returns job_id."""
    from database import AsyncSessionLocal
    from services.analysis import analyze_asset
    from workers.job_queue import get_job_queue

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
    from database import AsyncSessionLocal
    from services.caption import generate_caption
    from workers.job_queue import get_job_queue

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
    from database import AsyncSessionLocal
    from services.duplicate import find_duplicates
    from workers.job_queue import get_job_queue

    queue = get_job_queue()

    async def _run() -> dict:
        async with AsyncSessionLocal() as db:
            clusters = await find_duplicates(project_id, db)
            return {"clusters_found": len(clusters)}

    return await queue.submit(_run, job_type="duplicate_scan")


async def queue_export_sidecars_task(
    project_id: str,
    asset_ids: list[str],
    output_dir: str | None,
    job_id: str | None = None,
) -> str:
    """Queue sidecar .txt file export for a set of assets. Returns job_id."""
    from database import AsyncSessionLocal
    from services.caption import CaptionService
    from workers.job_queue import get_job_queue

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

    return await queue.submit(_run, job_type="export_sidecars")
