"""API tests for the asynchronous job workflow: POST /solve -> job_id -> GET /jobs/{id}."""
import time

import pytest
from fastapi.testclient import TestClient

from solver.api import app

client = TestClient(app)


def wait_for_job(job_id: str, timeout_seconds: float = 120.0) -> dict:
    """Poll /jobs/{id} until the job is finished or failed; fail the test on timeout."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        response = client.get(f"/jobs/{job_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in ("done", "failed"):
            return body
        time.sleep(0.2)
    pytest.fail(f"Job {job_id} did not finish within {timeout_seconds} s")


def test_solve_returns_job_id_immediately():
    response = client.post("/solve", json={"method": "priority_list", "scenario": "small"})

    assert response.status_code == 202
    body = response.json()
    assert body["job_id"]
    assert body["status"] in ("queued", "running")


def test_priority_list_job_finishes_with_result_and_metrics():
    job_id = client.post(
        "/solve",
        json={"method": "priority_list", "scenario": "small", "horizon": "day", "month": 1},
    ).json()["job_id"]

    job = wait_for_job(job_id)

    assert job["status"] == "done"
    result = job["result"]
    assert result["feasible"] is True
    assert result["total_cost_eur"] > 0
    assert result["solve_time_ms"] > 0
    assert result["num_variables"] > 0
    assert result["scenario"] == "small"
    assert result["horizon"] == "day"
    assert len(result["load"]) == result["T"]


def test_exact_job_accepts_time_limit_and_mip_gap():
    job_id = client.post(
        "/solve",
        json={
            "method": "exact",
            "scenario": "small",
            "horizon": "day",
            "month": 1,
            "time_limit": 60,
            "mip_gap": 0.05,
        },
    ).json()["job_id"]

    job = wait_for_job(job_id)

    assert job["status"] == "done"
    assert job["result"]["feasible"] is True


def test_unknown_job_returns_404():
    assert client.get("/jobs/does-not-exist").status_code == 404


@pytest.mark.parametrize(
    "payload, expected_status",
    [
        ({"scenario": "huge"}, 400),
        ({"horizon": "year"}, 400),
        ({"month": 13}, 400),
        ({"method": "magic"}, 400),
        ({"method": "ea"}, 400),
        ({"time_limit": 0}, 422),
        ({"time_limit": 100000}, 422),
        ({"mip_gap": -0.1}, 422),
        ({"mip_gap": 2}, 422),
    ],
)
def test_invalid_requests_are_rejected(payload, expected_status):
    response = client.post("/solve", json=payload)

    assert response.status_code == expected_status


def test_cors_allows_browser_origin():
    response = client.options(
        "/solve",
        headers={
            "Origin": "https://example.vercel.app",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] in ("*", "https://example.vercel.app")
