"""Tests for Prometheus metrics endpoint exposed by the orchestrator."""
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

import orchestrator.main as main_module  # noqa: E402
from orchestrator.main import app  # noqa: E402
from orchestrator.models import Job, JobResult, JobStatus, ResourceProfile, Node  # noqa: E402
from orchestrator.state import STORE  # noqa: E402


def test_metrics_endpoint_returns_metrics():
    client = TestClient(app)

    resp = client.get("/metrics")
    assert resp.status_code == 200
    text = resp.text

    # Ensure our metric names are present
    assert "edgecompute_jobs_submitted_total" in text
    assert "edgecompute_jobs_completed_total" in text
    assert "edgecompute_jobs_failed_total" in text
    assert "edgecompute_job_runtime_seconds" in text


def test_metrics_observation_failure_is_logged(monkeypatch, caplog):
    STORE.nodes.clear()
    STORE.jobs.clear()
    STORE.queue.clear()

    node = Node(
        node_id="node-metrics-test",
        tier=2,
        resources=ResourceProfile(cpu_cores=2.0, ram_gb=4.0, gpu_count=0),
        region="test-region",
    )
    job = Job(
        job_id="job-metrics-test",
        payload="metric payload",
        requirements=ResourceProfile(cpu_cores=1.0, ram_gb=1.0, gpu_count=0),
        assigned_at=100.0,
        status=JobStatus.ASSIGNED,
        assigned_node_id=node.node_id,
    )
    job.completed_at = 110.0
    STORE.jobs[job.job_id] = job
    node.current_job_id = job.job_id

    def boom(*args, **kwargs):
        raise RuntimeError("prometheus exploded")

    monkeypatch.setattr(main_module.JOB_RUNTIME_SECONDS, "observe", boom)

    with caplog.at_level(logging.ERROR):
        main_module._handle_job_result(
            node,
            JobResult(
                job_id=job.job_id,
                success=True,
                latency_ms=1000.0,
                output="ok",
                error=None,
            ),
        )

    assert any("failed to record job runtime metric" in record.message for record in caplog.records)
