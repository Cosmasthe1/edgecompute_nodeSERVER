"""FastAPI endpoint tests for the orchestrator main app."""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator.main import app  # noqa: E402
from orchestrator.state import STORE  # noqa: E402


@pytest.fixture(autouse=True)
def reset_store():
    STORE.nodes.clear()
    STORE.jobs.clear()
    STORE.queue.clear()
    yield
    STORE.nodes.clear()
    STORE.jobs.clear()
    STORE.queue.clear()


def test_register_node_endpoint_and_nodes_list_endpoint():
    client = TestClient(app)
    resp = client.post(
        "/nodes/register",
        json={
            "tier": 2,
            "resources": {"cpu_cores": 4.0, "ram_gb": 8.0, "gpu_count": 0},
            "region": "nairobi-ke",
            "lat": -1.286, "lon": 36.817,
            "energy_cost_per_kwh": 0.12,
        },
    )

    assert resp.status_code == 200
    node_id = resp.json()["node_id"]
    assert node_id

    list_resp = client.get("/nodes")
    assert list_resp.status_code == 200
    payload = list_resp.json()
    assert any(item["node_id"] == node_id for item in payload)


def test_submit_job_endpoint_creates_job_and_get_job_returns_status():
    client = TestClient(app)
    resp = client.post(
        "/jobs",
        json={
            "payload": "hello world",
            "requirements": {"cpu_cores": 1.0, "ram_gb": 2.0, "gpu_count": 0},
            "origin_lat": -1.28,
            "origin_lon": 36.82,
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "queued"
    job_id = body["job_id"]

    job_resp = client.get(f"/jobs/{job_id}")
    assert job_resp.status_code == 200
    assert job_resp.json()["job_id"] == job_id
    assert job_resp.json()["status"] == "queued"


def test_get_job_returns_404_for_unknown_job_id():
    client = TestClient(app)

    resp = client.get("/jobs/unknown-job")

    assert resp.status_code == 404
    assert resp.json()["detail"] == "unknown job_id"


def test_nodes_list_endpoint_returns_online_boolean_field():
    client = TestClient(app)
    client.post(
        "/nodes/register",
        json={
            "tier": 2,
            "resources": {"cpu_cores": 2.0, "ram_gb": 4.0, "gpu_count": 0},
            "region": "demo",
        },
    )

    resp = client.get("/nodes")
    assert resp.status_code == 200
    payload = resp.json()
    assert len(payload) == 1
    assert "online" in payload[0]
    assert payload[0]["online"] is True
