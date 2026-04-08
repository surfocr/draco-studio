"""Extended tests for workers/job_queue.py."""
from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from workers.job_queue import Job, JobQueue


@pytest.fixture
def isolated_job_queue(engine, monkeypatch):
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("workers.job_queue.AsyncSessionLocal", session_factory)
    JobQueue._instance = None
    queue = JobQueue.instance()
    yield queue
    JobQueue._instance = None


@pytest.mark.asyncio
async def test_get_status_returns_job(isolated_job_queue):
    """submit then get_status returns a Job with the correct type."""
    queue = isolated_job_queue
    await queue.start()

    async def _noop():
        return "ok"

    job_id = await queue.submit(_noop, job_type="status_check")
    job = queue.get_status(job_id)
    assert job is not None
    assert isinstance(job, Job)
    assert job.type == "status_check"
    await queue.stop()


@pytest.mark.asyncio
async def test_get_status_returns_none_for_unknown(isolated_job_queue):
    """get_status for a non-existent id returns None."""
    queue = isolated_job_queue
    assert queue.get_status("nonexistent") is None


@pytest.mark.asyncio
async def test_list_job_ids_returns_submitted_ids(isolated_job_queue):
    """submit 3 jobs, list_job_ids returns all 3."""
    queue = isolated_job_queue

    async def _noop():
        return None

    ids = []
    for _ in range(3):
        ids.append(await queue.submit(_noop, job_type="list_test"))

    listed = queue.list_job_ids()
    for jid in ids:
        assert jid in listed


@pytest.mark.asyncio
async def test_cancel_pending_job(isolated_job_queue):
    """Cancel a pending job (queue not started) returns True and sets status."""
    queue = isolated_job_queue

    async def _noop():
        return None

    job_id = await queue.submit(_noop, job_type="cancel_test")
    assert queue.get_status(job_id).status == "pending"
    result = await queue.cancel(job_id)
    assert result is True
    assert queue.get_status(job_id).status == "cancelled"


@pytest.mark.asyncio
async def test_cancel_nonexistent_returns_false(isolated_job_queue):
    """cancel() on a non-existent job returns False."""
    queue = isolated_job_queue
    result = await queue.cancel("nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_cancel_already_done_returns_false(isolated_job_queue):
    """cancel() on a completed job returns False."""
    queue = isolated_job_queue

    async def _fast():
        return "done"

    await queue.start()
    job_id = await queue.submit(_fast, job_type="done_cancel")

    for _ in range(40):
        job = queue.get_status(job_id)
        if job and job.status == "done":
            break
        await asyncio.sleep(0.05)

    result = await queue.cancel(job_id)
    assert result is False
    await queue.stop()


@pytest.mark.asyncio
async def test_update_progress(isolated_job_queue):
    """update_progress sets progress and message on the job."""
    queue = isolated_job_queue

    async def _noop():
        return None

    job_id = await queue.submit(_noop, job_type="progress_test")
    await queue.update_progress(job_id, 42, "almost halfway")

    job = queue.get_status(job_id)
    assert job.progress == 42
    assert job.message == "almost halfway"


@pytest.mark.asyncio
async def test_eviction_when_at_capacity(isolated_job_queue, monkeypatch):
    """When MAX_JOBS is reached, the oldest job is evicted."""
    queue = isolated_job_queue
    monkeypatch.setattr(JobQueue, "MAX_JOBS", 3)

    async def _noop():
        return None

    ids = []
    for i in range(4):
        ids.append(await queue.submit(_noop, job_type=f"evict_{i}"))

    # The first job should have been evicted
    assert queue.get_status(ids[0]) is None
    # The remaining 3 should still exist
    for jid in ids[1:]:
        assert queue.get_status(jid) is not None


@pytest.mark.asyncio
async def test_failed_job_records_error(isolated_job_queue):
    """A task that raises records status='failed' and the error message."""
    queue = isolated_job_queue

    async def _boom():
        raise ValueError("something went wrong")

    await queue.start()
    job_id = await queue.submit(_boom, job_type="fail_test")

    for _ in range(40):
        job = queue.get_status(job_id)
        if job and job.status in ("done", "failed"):
            break
        await asyncio.sleep(0.05)

    job = queue.get_status(job_id)
    assert job.status == "failed"
    assert job.error == "something went wrong"
    await queue.stop()
