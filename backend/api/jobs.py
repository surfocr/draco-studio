"""Job status and WebSocket progress router."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import AsyncSessionLocal, get_db
from models.job_run import JobRun
from workers.job_queue import get_job_queue

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
async def list_jobs(db: AsyncSession = Depends(get_db)) -> list[dict]:
    result = await db.execute(select(JobRun).order_by(JobRun.created_at.desc()).limit(200))
    return [_serialize_job(job) for job in result.scalars().all()]


@router.get("/{job_id}")
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    job = await db.get(JobRun, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _serialize_job(job)


@router.delete("/{job_id}")
async def cancel_job(job_id: str) -> dict:
    queue = get_job_queue()
    ok = await queue.cancel(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Job not found or already complete")
    return {"ok": True, "job_id": job_id}


@router.websocket("/ws/{job_id}")
async def job_progress_ws(websocket: WebSocket, job_id: str) -> None:
    """WebSocket endpoint for real-time job progress updates."""
    await websocket.accept()
    try:
        while True:
            async with AsyncSessionLocal() as db:
                job = await db.get(JobRun, job_id)
            if not job:
                await websocket.send_json({"error": "Job not found"})
                break

            await websocket.send_json(_serialize_job(job))

            if job.status in ("done", "failed", "cancelled"):
                break

            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        logger.debug("WebSocket disconnected for job %s", job_id)
    except Exception as exc:
        logger.warning("WebSocket error for job %s: %s", job_id, exc)
    finally:
        try:
            await websocket.close()
        except Exception:
            pass


def _serialize_job(job: JobRun) -> dict:
    result = job.result
    if isinstance(result, dict) and set(result.keys()) == {"value"}:
        result = result["value"]
    return {
        "id": job.id,
        "type": job.type,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "result": result,
        "error": job.error,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }
