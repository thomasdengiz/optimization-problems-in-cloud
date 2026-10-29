"""
Unit Commitment API
GET  /health
GET  /methods
POST /solve        -> 202 {job_id, status}   (runs asynchronously)
GET  /jobs/{id}    -> {status: queued|running|done|failed, result|error}
POST /benchmark

Environment variables:
  CORS_ORIGINS    comma-separated allowed browser origins (default: *)
  MAX_TIME_LIMIT  upper bound for the exact solver time limit in seconds (default: 300)
  SOLVER_WORKERS  number of parallel worker processes (default: 2)
"""
import os
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .exact         import HORIZONS, estimate_exact_memory_mb, solve_exact
from .jobs          import DATA_DIR, job_manager, logger, memory_limit_mb
from .priority_list import solve_priority_list

MAX_TIME_LIMIT = int(os.environ.get("MAX_TIME_LIMIT", "300"))
CORS_ORIGINS   = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    """Log the server configuration at startup; stop the worker processes at shutdown."""
    logger.info(
        "Server started: memory_limit_mb=%s workers=%s max_time_limit=%s cors_origins=%s",
        memory_limit_mb(), os.environ.get("SOLVER_WORKERS", "2"), MAX_TIME_LIMIT, CORS_ORIGINS,
    )
    yield
    job_manager.shutdown()


app = FastAPI(title="Unit Commitment Solver", version="1.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

METHODS = {
    "exact": {
        "label":     "Exact (HiGHS/Pyomo)",
        "available": True,
        "scenarios": ["small", "medium", "large"],
        "description": "MIP formulation solved with HiGHS. Larger scenarios/horizons may hit the time limit.",
    },
    "priority_list": {
        "label":     "Priority List Heuristic",
        "available": True,
        "scenarios": ["small", "medium", "large"],
        "description": "Classic merit-order heuristic from power systems literature.",
    },
    "ea": {
        "label":     "Evolutionary Algorithm",
        "available": False,
        "scenarios": [],
        "description": "Coming soon.",
    },
    "pso": {
        "label":     "Particle Swarm Optimization",
        "available": False,
        "scenarios": [],
        "description": "Coming soon.",
    },
    "custom": {
        "label":     "Custom Heuristic",
        "available": False,
        "scenarios": [],
        "description": "Coming soon.",
    },
    "ml": {
        "label":     "ML-based Heuristic",
        "available": False,
        "scenarios": [],
        "description": "Coming soon.",
    },
}


class SolveRequest(BaseModel):
    """Input of POST /solve and /benchmark."""
    scenario: str = "small"   # small | medium | large
    horizon:  str = "day"     # day | week | month
    month:    int = 1         # 1-12
    method:   str = "priority_list"
    time_limit: int = Field(120, gt=0, le=MAX_TIME_LIMIT)    # seconds, exact method only
    mip_gap:  float | None = Field(None, ge=0, le=1)         # relative gap, exact method only


@app.get("/health")
def health():
    return {"status": "ok", "service": "unit-commitment"}


@app.get("/methods")
def get_methods():
    return METHODS


@app.post("/solve", status_code=202)
def solve(req: SolveRequest):
    """Validate the request, start the optimization as a background job and return its job_id."""
    if req.scenario not in ["small", "medium", "large"]:
        raise HTTPException(400, f"Invalid scenario: {req.scenario}")
    if req.horizon not in HORIZONS:
        raise HTTPException(400, f"Invalid horizon: {req.horizon}")
    if not 1 <= req.month <= 12:
        raise HTTPException(400, "Month must be between 1 and 12")
    if req.method not in METHODS:
        raise HTTPException(400, f"Unknown method: {req.method}")
    if not METHODS[req.method]["available"]:
        raise HTTPException(400, f"Method '{req.method}' not yet implemented")
    if req.scenario not in METHODS[req.method]["scenarios"]:
        raise HTTPException(400, f"Method '{req.method}' not available for scenario '{req.scenario}'")

    # The exact model needs much memory for big scenarios. If the server clearly does not have
    # enough, refuse early instead of letting the operating system kill the worker.
    limit = memory_limit_mb()
    if req.method == "exact" and limit is not None:
        needed = estimate_exact_memory_mb(req.scenario, req.month, DATA_DIR, req.horizon)
        if needed > limit:
            raise HTTPException(
                400,
                f"Für diese Kombination braucht die exakte Methode etwa {needed:.0f} MB Arbeitsspeicher, "
                f"der Server hat {limit:.0f} MB. Bitte ein kleineres Szenario, einen kürzeren Zeitraum "
                "oder die Heuristik wählen.",
            )

    try:
        job_id = job_manager.submit(
            method=req.method,
            scenario=req.scenario,
            month=req.month,
            horizon=req.horizon,
            time_limit=req.time_limit,
            mip_gap=req.mip_gap,
        )
    except Exception as error:
        # An HTTPException keeps the CORS headers, so the browser can show the message
        logger.exception("Could not start job")
        raise HTTPException(503, f"Auftrag konnte nicht gestartet werden: {error}") from error
    return {"job_id": job_id, "status": "queued"}


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    """Return the status of a job and, once finished, its result or error message."""
    job = job_manager.get(job_id)
    if job is None:
        raise HTTPException(
            404,
            f"Unknown job: {job_id} (the server may have restarted since the job was submitted)",
        )
    return job


@app.post("/benchmark")
def benchmark(req: SolveRequest):
    """Run all available methods for the given scenario and compare results."""
    available = [
        m for m, v in METHODS.items()
        if v["available"] and req.scenario in v["scenarios"]
    ]
    results = {}

    for method in available:
        start = time.perf_counter()
        try:
            req.method = method
            if method == "exact":
                r = solve_exact(req.scenario, req.month, DATA_DIR, req.horizon)
            elif method == "priority_list":
                r = solve_priority_list(req.scenario, req.month, DATA_DIR, req.horizon)
            elapsed = (time.perf_counter() - start) * 1000
            results[method] = {
                "label":          METHODS[method]["label"],
                "total_cost_eur": r["total_cost_eur"],
                "feasible":       r["feasible"],
                "solve_time_ms":  round(elapsed, 2),
            }
        except Exception as e:
            results[method] = {"error": str(e)}

    return results
