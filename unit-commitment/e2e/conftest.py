"""
Fixtures for the browser (end-to-end) tests.

By default the fixtures start the API (port 8000) and a static file server for the
frontend (port 3000) as local processes. If E2E_EXTERNAL=1 is set, both are expected to be
running already (e.g. the API inside the Docker container started by the CI).
"""
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
API_URL = "http://localhost:8000"
FRONTEND_URL = "http://localhost:3000"


def wait_until_up(url: str, timeout_seconds: float = 60.0) -> None:
    """Block until the URL answers with HTTP 200, otherwise fail."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.5)
    raise RuntimeError(f"{url} did not come up within {timeout_seconds} s")


@pytest.fixture(scope="session", autouse=True)
def servers():
    """Start (or reuse) backend and frontend for the whole test session."""
    processes = []
    if os.environ.get("E2E_EXTERNAL") != "1":
        processes.append(subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "solver.api:app", "--port", "8000"],
            cwd=PROJECT_ROOT,
        ))
        processes.append(subprocess.Popen(
            [sys.executable, "-m", "http.server", "3000", "--directory", "frontend"],
            cwd=PROJECT_ROOT,
        ))
    wait_until_up(f"{API_URL}/health")
    wait_until_up(f"{FRONTEND_URL}/index.html")
    yield
    for process in processes:
        process.terminate()


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Open the browser with a German locale, so the page starts in German (as the tests expect)."""
    return {**browser_context_args, "locale": "de-DE"}


@pytest.fixture
def app_page(page):
    """Open the web page against the local backend and wait until the methods are loaded.

    config.js points to the production backend, so the tests replace it with a config
    that points to the local backend (or the Docker container started by the CI).
    """
    page.route(
        "**/config.js",
        lambda route: route.fulfill(
            content_type="application/javascript",
            body=f'window.APP_CONFIG = {{ API_BASE_URL: "{API_URL}" }};',
        ),
    )
    page.goto(FRONTEND_URL)
    page.wait_for_function("document.querySelectorAll('#method option').length > 0", timeout=60000)
    return page
