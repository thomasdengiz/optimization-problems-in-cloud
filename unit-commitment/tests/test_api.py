import sys
from pathlib import Path

from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from solver.api import app


client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_methods_endpoint_lists_available_methods():
    response = client.get("/methods")

    assert response.status_code == 200
    methods = response.json()
    assert methods["exact"]["available"] is True
    assert methods["priority_list"]["available"] is True
