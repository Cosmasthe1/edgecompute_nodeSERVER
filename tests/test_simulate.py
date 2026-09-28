"""Tests for the simulator helper functions."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import simulator.simulate as simulate  # noqa: E402


class DummyResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("bad response")

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, *, jobs, node_summary):
        self.jobs = jobs
        self.node_summary = node_summary
        self.calls: list[tuple[str, dict | None]] = []

    def post(self, url: str, json: dict):
        self.calls.append((url, json))
        next_id = len(self.calls) - 1
        return DummyResponse({"job_id": f"job-{next_id}"})

    def get(self, url: str):
        if url.endswith("/nodes"):
            return DummyResponse(self.node_summary)
        job_id = url.rsplit("/", 1)[1]
        return DummyResponse(self.jobs[job_id])


def test_submit_jobs_posts_expected_jobs(monkeypatch):
    choices = iter([0.5, 1.0, 0, 0.0, 2.0, 1.0, 0, 0.0, 1.0, 2.0, 0, 8.0, 0.5, 1.0, 0, 0.0])
    monkeypatch.setattr(simulate.random, "choice", lambda seq: next(choices))
    monkeypatch.setattr(simulate.time, "sleep", lambda *_args, **_kwargs: None)

    class FakeHttpxClient:
        def __init__(self, *args, **kwargs):
            self.calls = []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, url: str, json: dict):
            self.calls.append((url, json))
            return DummyResponse({"job_id": f"job-{len(self.calls)}"})

    monkeypatch.setattr(simulate.httpx, "Client", FakeHttpxClient)

    job_ids = simulate.submit_jobs("http://localhost:8000", 2)

    assert job_ids == ["job-1", "job-2"]
    assert len(job_ids) == 2


def test_wait_and_report_prints_summary(monkeypatch, capsys):
    job_payloads = {
        "job-1": {"status": "completed", "completed_at": 120.0, "submitted_at": 110.0},
        "job-2": {"status": "completed", "completed_at": 125.0, "submitted_at": 115.0},
    }
    node_payload = [
        {"node_id": "n1", "tier": 1, "online": True, "reliability_score": 0.9, "credit_balance": 3.0},
    ]

    monkeypatch.setattr(simulate.time, "sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(simulate.time, "time", lambda: 100.0)
    monkeypatch.setattr(
        simulate.httpx,
        "Client",
        lambda *args, **kwargs: FakeClient(jobs=job_payloads, node_summary=node_payload),
    )

    simulate.wait_and_report("http://localhost:8000", ["job-1", "job-2"], timeout_s=10.0)

    out = capsys.readouterr().out
    assert "submitted:   2" in out
    assert "completed:   2" in out
    assert "avg JCT:     10.00s" in out
    assert "n1" in out
