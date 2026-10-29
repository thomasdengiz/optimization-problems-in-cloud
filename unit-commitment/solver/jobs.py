"""
Asynchronous job handling for long-running optimizations.

POST /solve submits a job and returns a job_id immediately; the web page then polls
GET /jobs/{job_id}. Jobs run in separate worker processes so the API stays responsive
and a CPU-heavy solve cannot block other requests. Jobs are kept in memory only.
"""
import logging
import multiprocessing
import os
import time
import uuid
from concurrent.futures import Future, ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool

from .exact import solve_exact
from .priority_list import solve_priority_list

# Log lines end up in the container console (Azure log stream). Worker processes import this
# module as well, so they get the same setup.
# Only our own logger gets a handler. A handler on the root logger would also print Pyomo's
# INFO messages, and Pyomo captures the solver's console output into exactly those messages,
# which makes the program loop endlessly (and hang the solve).
logger = logging.getLogger("unit_commitment")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_handler)

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
MAX_JOBS_KEPT = 200  # oldest finished jobs are dropped beyond this number

# Shown to the user when the operating system killed a worker process
WORKER_KILLED_MESSAGE = (
    "Der Rechenprozess wurde vom Betriebssystem beendet, vermutlich wegen zu wenig "
    "Arbeitsspeicher auf dem Server. Bitte ein kleineres Szenario oder einen kürzeren "
    "Zeitraum wählen."
)


def memory_limit_mb() -> float | None:
    """Memory limit of the container in MB (read from the cgroup files), or None if unknown."""
    for path in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            with open(path) as file:
                raw = file.read().strip()
        except OSError:
            continue
        if raw.isdigit() and int(raw) < 1 << 50:  # huge numbers mean "no limit"
            return int(raw) / 1024 / 1024
    return None


def peak_memory_mb() -> float | None:
    """Highest memory use of this process so far in MB (Linux only), or None if unknown."""
    try:
        import resource
    except ImportError:  # Windows has no resource module
        return None
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024  # Linux reports KB


def run_solve(
    method: str,
    scenario: str,
    month: int,
    horizon: str,
    time_limit: int,
    mip_gap: float | None,
) -> dict:
    """Run one optimization (executed inside a worker process) and return the result dict.

    Start, end and failures are logged so problems can be traced in the server logs.
    """
    description = f"method={method} scenario={scenario} horizon={horizon} month={month}"
    logger.info("Job started: %s time_limit=%s mip_gap=%s", description, time_limit, mip_gap)
    start = time.perf_counter()
    try:
        if method == "exact":
            result = solve_exact(scenario, month, DATA_DIR, horizon, time_limit=time_limit, mip_gap=mip_gap)
        elif method == "priority_list":
            result = solve_priority_list(scenario, month, DATA_DIR, horizon)
        else:
            raise ValueError(f"Unknown method: {method}")
    except Exception:
        logger.exception("Job failed: %s", description)  # includes the traceback
        raise

    duration = time.perf_counter() - start
    result["solve_time_ms"] = round(duration * 1000, 2)
    result["scenario"] = scenario
    result["horizon"] = horizon
    result["month"] = month
    peak = peak_memory_mb()
    logger.info(
        "Job finished: %s feasible=%s cost=%.0f duration=%.1fs peak_memory_mb=%s",
        description, result["feasible"], result["total_cost_eur"], duration,
        None if peak is None else round(peak),
    )
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

    def submit(self, target=run_solve, **params) -> str:
        """Start a job (target is run_solve unless a test passes another function) and return its job_id.

        If the worker pool is broken because a worker was killed earlier, a new pool is created.
        """
        self._drop_old_jobs()
        job_id = uuid.uuid4().hex
        try:
            future = self._get_executor().submit(target, **params)
        except BrokenProcessPool:
            logger.error("Worker pool is broken (a worker was killed, probably out of memory). Creating a new pool.")
            self._reset_executor()
            future = self._get_executor().submit(target, **params)
        self._jobs[job_id] = future
        logger.info("Job %s submitted (%d jobs stored)", job_id, len(self._jobs))
        return job_id

    def get(self, job_id: str) -> dict | None:
        """Return {job_id, status, result|error} for a job, or None if the id is unknown."""
        future = self._jobs.get(job_id)
        if future is None:
            return None

        if not future.done():
            return {"job_id": job_id, "status": "running" if future.running() else "queued"}

        error = future.exception()
        if isinstance(error, BrokenProcessPool):
            logger.error("Job %s failed: a worker process was killed (probably out of memory)", job_id)
            return {"job_id": job_id, "status": "failed", "error": WORKER_KILLED_MESSAGE}
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

    def _reset_executor(self) -> None:
        """Throw away the current (broken) process pool; a new one is created on the next use."""
        if self._executor is not None:
            self._executor.shutdown(wait=False, cancel_futures=True)
            self._executor = None

    def shutdown(self) -> None:
        """Stop the worker processes (called when the API shuts down)."""
        self._reset_executor()


job_manager = JobManager()
