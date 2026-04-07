from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from models.job_run import JobRun
from workers.job_queue import JobQueue


@pytest.fixture
def isolated_job_queue(engine, monkeypatch):
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("workers.job_queue.AsyncSessionLocal", session_factory)
    JobQueue._instance = None
    queue = JobQueue.instance()
    yield queue
    JobQueue._instance = None


@pytest.mark.asyncio
async def test_job_queue_persists_completed_job(engine, isolated_job_queue):
    queue = isolated_job_queue

    async def _run() -> dict:
        return {"ok": True}

    await queue.start()
    job_id = await queue.submit(_run, job_type="test_job")
    for _ in range(20):
        job = queue.get_status(job_id)
        if job and job.status == "done":
            break
        await asyncio.sleep(0.05)
    await queue.stop()

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        job = await db.get(JobRun, job_id)

    assert job is not None
    assert job.type == "test_job"
    assert job.status == "done"
    assert job.progress == 100
    assert job.result == {"ok": True}
    assert job.finished_at is not None


@pytest.mark.asyncio
async def test_job_queue_marks_interrupted_jobs_on_start(engine, isolated_job_queue):
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        db.add(JobRun(id="stale-job", type="caption", status="running"))
        await db.commit()

    queue = isolated_job_queue
    await queue.start()
    await queue.stop()

    async with session_factory() as db:
        stale = await db.get(JobRun, "stale-job")

    assert stale is not None
    assert stale.status == "failed"
    assert stale.error == "Job interrupted by application restart"
    assert stale.finished_at is not None


@pytest.mark.asyncio
async def test_job_queue_stop_cancels_running_async_jobs(engine, isolated_job_queue):
    queue = isolated_job_queue
    started = asyncio.Event()

    async def _run_forever() -> None:
        started.set()
        await asyncio.sleep(60)

    await queue.start()
    job_id = await queue.submit(_run_forever, job_type="long_running")
    await asyncio.wait_for(started.wait(), timeout=1)
    await asyncio.sleep(0.05)
    await queue.stop()

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as db:
        job = await db.get(JobRun, job_id)

    assert job is not None
    assert job.status == "cancelled"
    assert job.finished_at is not None
