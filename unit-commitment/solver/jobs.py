"""
Asynchronous job handling for long-running optimizations.

POST /solve submits a job and returns a job_id immediately; the web page then polls
GET /jobs/{job_id}. Jobs run in separate worker processes so the API stays responsive
and a CPU-heavy solve cannot block other requests. Jobs are kept in memory only.
"""
import multiprocessing
import os
import time
import uuid
from concurrent.futures import Future, ProcessPoolExecutor

from .exact import solve_exact
from .priority_list import solve_priority_list

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
MAX_JOBS_KEPT = 200  # oldest finished jobs are dropped beyond this number


def run_solve(
    method: str,
    scenario: str,
    month: int,
    horizon: str,
    time_limit: int,
    mip_gap: float | None,
) -> dict:
    """Run one optimization (executed inside a worker process) and return the result dict."""
    start = time.perf_counter()
    if method == "exact":
        result = solve_exact(scenario, month, DATA_DIR, horizon, time_limit=time_limit, mip_gap=mip_gap)
    elif method == "priority_list":
        result = solve_priority_list(scenario, month, DATA_DIR, horizon)
    else:
        raise ValueError(f"Unknown method: {method}")

    result["solve_time_ms"] = round((time.perf_counter() - start) * 1000, 2)
    result["scenario"] = scenario
    result["horizon"] = horizon
    result["month"] = month
    return result


class JobManager:
    """Keeps track of submitted jobs and runs them in a pool of worker processes."""

    def __init__(self, max_workers: int | None = None) -> None:
        """Remember the worker count; the process pool itself is created lazily on first use."""
        self._max_workers = max_workers or int(os.environ.get("SOLVER_WORKERS", "2"))
        self._executor: ProcessPoolExecutor | None = None
        self._jobs: dict[str, Future] = {}

    def _get_executor(self) -> ProcessPoolExecutor:
        """Create the process pool on first use ('spawn' behaves the same on Windows and Linux)."""
        if self._executor is None:
            self._executor = ProcessPoolExecutor(
                max_workers=self._max_workers,
                mp_context=multiprocessing.get_context("spawn"),
            )
        return self._executor

    def submit(self, **params) -> str:
        """Start a job with the given run_solve parameters and return its job_id."""
        self._drop_old_jobs()
        job_id = uuid.uuid4().hex
        self._jobs[job_id] = self._get_executor().submit(run_solve, **params)
        return job_id

    def get(self, job_id: str) -> dict | None:
        """Return {job_id, status, result|error} for a job, or None if the id is unknown."""
        future = self._jobs.get(job_id)
        if future is None:
            return None

        if not future.done():
            return {"job_id": job_id, "status": "running" if future.running() else "queued"}

        error = future.exception()
        if error is not None:
            return {"job_id": job_id, "status": "failed", "error": f"{type(error).__name__}: {error}"}
        return {"job_id": job_id, "status": "done", "result": future.result()}

    def _drop_old_jobs(self) -> None:
        """Forget the oldest finished jobs once more than MAX_JOBS_KEPT are stored."""
        excess = len(self._jobs) - MAX_JOBS_KEPT
        for job_id in list(self._jobs):
            if excess <= 0:
                break
            if self._jobs[job_id].done():
                del self._jobs[job_id]
                excess -= 1

    def shutdown(self) -> None:
        """Stop the worker processes (called when the API shuts down)."""
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None


job_manager = JobManager()
