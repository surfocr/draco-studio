"""
Benchmark router — compare caption/face/embedding providers on a sample of assets.
"""
from __future__ import annotations

import logging
import time
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from providers.registry import get_registry

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])


class BenchmarkRunRequest(BaseModel):
    provider_type: str
    provider_names: list[str]
    asset_ids: list[str]


class ProviderResult(BaseModel):
    provider: str
    latency_ms_avg: float
    latency_ms_p95: float
    success_rate: float
    error_count: int
    sample_outputs: list[dict]
    error: str | None = None


@router.get("/providers/{provider_type}")
async def list_benchmark_providers(provider_type: str) -> dict:
    """Return providers registered for the given type."""
    registry = get_registry()
    providers = registry.list_available(provider_type)
    return {"providers": providers, "provider_type": provider_type}


@router.post("/run")
async def run_benchmark(
    body: BenchmarkRunRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Run a benchmark comparing multiple providers on a set of assets.
    Returns results synchronously for small sample sets (<=20 assets).
    Returns a job_id for larger sets.
    """
    if len(body.provider_names) < 2:
        raise HTTPException(status_code=400, detail="Provide at least 2 providers to compare")
    if not body.asset_ids:
        raise HTTPException(status_code=400, detail="No asset IDs provided")

    from workers.job_queue import get_job_queue
    from models.asset import Asset

    queue = get_job_queue()

    async def _run_benchmark() -> list[dict]:
        registry = get_registry()
        results: list[dict] = []

        for provider_name in body.provider_names:
            provider = registry.get(body.provider_type, provider_name)
            if not provider:
                results.append({
                    "provider": provider_name,
                    "latency_ms_avg": 0,
                    "latency_ms_p95": 0,
                    "success_rate": 0,
                    "error_count": len(body.asset_ids),
                    "sample_outputs": [],
                    "error": f"Provider '{provider_name}' not found in registry",
                })
                continue

            latencies: list[float] = []
            errors = 0
            sample_outputs: list[dict] = []

            for asset_id in body.asset_ids:
                asset = await db.get(Asset, asset_id)
                if not asset or not asset.filepath:
                    errors += 1
                    continue

                t0 = time.monotonic()
                try:
                    if body.provider_type == "caption" and hasattr(provider, "generate"):
                        result = await provider.generate(asset.filepath, style="natural")
                        latency = (time.monotonic() - t0) * 1000
                        latencies.append(latency)
                        if len(sample_outputs) < 3:
                            sample_outputs.append({"asset": asset_id, "text": result.text})
                    else:
                        # Generic availability check for non-caption providers
                        await provider.is_available()
                        latency = (time.monotonic() - t0) * 1000
                        latencies.append(latency)
                        if len(sample_outputs) < 3:
                            sample_outputs.append({"asset": asset_id, "text": "(not a caption provider)"})
                except Exception as exc:
                    logger.warning("Benchmark error for %s on %s: %s", provider_name, asset_id, exc)
                    errors += 1

            total = len(body.asset_ids)
            success_count = total - errors
            sorted_lat = sorted(latencies) if latencies else [0.0]
            p95_idx = max(0, int(len(sorted_lat) * 0.95) - 1)

            results.append({
                "provider": provider_name,
                "latency_ms_avg": sum(sorted_lat) / len(sorted_lat),
                "latency_ms_p95": sorted_lat[p95_idx],
                "success_rate": success_count / total if total > 0 else 0.0,
                "error_count": errors,
                "sample_outputs": sample_outputs,
                "error": None,
            })

        return results

    job_id = await queue.submit(_run_benchmark)
    return {"job_id": job_id, "provider_count": len(body.provider_names), "asset_count": len(body.asset_ids)}
