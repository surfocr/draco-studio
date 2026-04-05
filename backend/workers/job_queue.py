"""
Async job queue — no Redis required for local mode.
Uses asyncio.Queue + ThreadPoolExecutor for CPU-bound tasks.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine

from config import settings

logger = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    type: str = "generic"
    status: str = "pending"          # pending/running/done/failed/cancelled
    progress: int = 0                # 0–100
    message: str = ""
    result: Any | None = None
    error: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


class JobQueue:
    """
    Singleton async job queue.

    - CPU-bound tasks run in a ThreadPoolExecutor.
    - Async tasks run directly on the event loop.
    - Jobs are retained in memory for status polling (max 1000, LRU eviction).
    """

    _instance: "JobQueue | None" = None
    MAX_JOBS = 1000

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Job] = asyncio.Queue()
        self._jobs: OrderedDict[str, Job] = OrderedDict()
        self._executor = ThreadPoolExecutor(max_workers=settings.MAX_WORKERS)
        self._running = False
        self._worker_task: asyncio.Task | None = None
        self._tasks: dict[str, Callable | Coroutine] = {}

    @classmethod
    def instance(cls) -> "JobQueue":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._worker_task = asyncio.create_task(self._worker())
        logger.info("JobQueue started (max_workers=%d)", settings.MAX_WORKERS)

    async def stop(self) -> None:
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        self._executor.shutdown(wait=False)
        logger.info("JobQueue stopped")

    async def submit(
        self,
        task_fn: Callable[..., Coroutine],
        *args: Any,
        job_type: str = "generic",
        **kwargs: Any,
    ) -> str:
        """Submit an async task. Returns job_id."""
        job_id = str(uuid.uuid4())
        job = Job(id=job_id, type=job_type)

        # Evict oldest if at capacity
        if len(self._jobs) >= self.MAX_JOBS:
            oldest_id = next(iter(self._jobs))
            del self._jobs[oldest_id]

        self._jobs[job_id] = job
        self._tasks[job_id] = (task_fn, args, kwargs)
        await self._queue.put(job)
        logger.debug("Submitted job %s (type=%s)", job_id[:8], job_type)
        return job_id

    def get_status(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list_job_ids(self) -> list[str]:
        return list(self._jobs.keys())

    async def cancel(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if not job:
            return False
        if job.status in ("done", "failed", "cancelled"):
            return False
        job.status = "cancelled"
        job.finished_at = datetime.now(timezone.utc)
        return True

    def update_progress(self, job_id: str, progress: int, message: str = "") -> None:
        job = self._jobs.get(job_id)
        if job:
            job.progress = progress
            job.message = message

    async def _worker(self) -> None:
        while self._running:
            try:
                job = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue

            if job.status == "cancelled":
                self._queue.task_done()
                continue

            task_info = self._tasks.pop(job.id, None)
            if task_info is None:
                self._queue.task_done()
                continue

            task_fn, args, kwargs = task_info
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)

            try:
                if asyncio.iscoroutinefunction(task_fn):
                    result = await task_fn(*args, **kwargs)
                else:
                    loop = asyncio.get_event_loop()
                    result = await loop.run_in_executor(
                        self._executor, lambda: task_fn(*args, **kwargs)
                    )

                job.result = result
                job.status = "done"
                job.progress = 100
                logger.debug("Job %s done", job.id[:8])

            except asyncio.CancelledError:
                job.status = "cancelled"
            except Exception as exc:
                job.status = "failed"
                job.error = str(exc)
                logger.exception("Job %s failed: %s", job.id[:8], exc)
            finally:
                job.finished_at = datetime.now(timezone.utc)
                self._queue.task_done()


_queue_instance: JobQueue | None = None


def get_job_queue() -> JobQueue:
    return JobQueue.instance()
