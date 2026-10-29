"""
Tests for the recovery of the worker pool.

If the operating system kills a worker (typically: out of memory), Python marks the whole
process pool as broken. The job manager must report this clearly and keep working afterwards.
"""
import os
import time

import pytest

from solver.jobs import JobManager, memory_limit_mb


def crash_worker(**_params):
    """Simulate the out-of-memory killer: the worker process disappears without a trace."""
    os._exit(1)


def quick_job(**_params):
    """A job that finishes immediately."""
    return {"ok": True}


def wait_for(manager: JobManager, job_id: str, timeout_seconds: float = 30.0) -> dict:
    """Poll the manager until the job is finished or failed."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        job = manager.get(job_id)
        if job["status"] in ("done", "failed"):
            return job
        time.sleep(0.1)
    pytest.fail("job did not finish in time")


@pytest.fixture
def manager():
    manager = JobManager(max_workers=1)
    yield manager
    manager.shutdown()


def test_killed_worker_is_reported_with_a_helpful_message(manager):
    job_id = manager.submit(target=crash_worker)

    job = wait_for(manager, job_id)

    assert job["status"] == "failed"
    assert "Arbeitsspeicher" in job["error"]


def test_manager_keeps_working_after_a_worker_was_killed(manager):
    wait_for(manager, manager.submit(target=crash_worker))

    job = wait_for(manager, manager.submit(target=quick_job))

    assert job["status"] == "done"
    assert job["result"] == {"ok": True}


def test_memory_limit_is_none_or_positive():
    limit = memory_limit_mb()

    assert limit is None or limit > 0
