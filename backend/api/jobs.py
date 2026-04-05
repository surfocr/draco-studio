"""Job status and WebSocket progress router."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from workers.job_queue import get_job_queue

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("")
async def list_jobs() -> list[dict]:
    queue = get_job_queue()
    return [queue.get_status(jid).to_dict() for jid in queue.list_job_ids()]


@router.get("/{job_id}")
async def get_job(job_id: str) -> dict:
    queue = get_job_queue()
    job = queue.get_status(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


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
    queue = get_job_queue()

    try:
        while True:
            job = queue.get_status(job_id)
            if not job:
                await websocket.send_json({"error": "Job not found"})
                break

            await websocket.send_json(job.to_dict())

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
