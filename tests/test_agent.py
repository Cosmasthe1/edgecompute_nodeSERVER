"""Unit tests for the node agent polling loop."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import node_agent  # noqa: E402
from agent.node_agent import NodeAgent  # noqa: E402


class DummyResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("bad response")

    def json(self):
        return self._payload


class DummyClient:
    def __init__(self, *, register_payload: dict | None = None, poll_payload: dict | None = None):
        self.register_payload = register_payload or {"node_id": "agent-123"}
        self.poll_payload = poll_payload or {"assigned_job": None}
        self.calls: list[tuple[str, dict]] = []

    def post(self, url: str, json: dict):
        self.calls.append((url, json))
        if "/nodes/register" in url:
            return DummyResponse(self.register_payload)
        if "/nodes/" in url and "/poll" in url:
            return DummyResponse(self.poll_payload)
        raise AssertionError(f"unexpected URL: {url}")


def test_register_sets_node_id_and_poll_interval():
    agent = NodeAgent("http://localhost:8000", 2, 4.0, 8.0, 0, "nairobi-ke", 3.0)
    agent.client = DummyClient(register_payload={"node_id": "agent-123", "poll_interval_seconds": 9.0})

    agent.register()

    assert agent.node_id == "agent-123"
    assert agent.poll_interval == 9.0


def test_execute_returns_success_result(monkeypatch):
    agent = NodeAgent("http://localhost:8000", 2, 4.0, 8.0, 0, "nairobi-ke", 0.5, fail_rate=0.0)

    times = iter([100.0, 100.5])
    monkeypatch.setattr(node_agent.time, "time", lambda: next(times))
    monkeypatch.setattr(node_agent.random, "uniform", lambda a, b: 0.5)
    monkeypatch.setattr(node_agent.random, "random", lambda: 0.2)

    result = agent._execute({"job_id": "job-456"})

    assert result["job_id"] == "job-456"
    assert result["success"] is True
    assert result["latency_ms"] == 500.0
    assert result["output"] == "ok"
    assert result["error"] is None


def test_poll_once_executes_and_buffers_result(monkeypatch):
    agent = NodeAgent("http://localhost:8000", 2, 4.0, 8.0, 0, "nairobi-ke", 0.5)
    agent.node_id = "agent-123"
    agent.client = DummyClient(
        poll_payload={
            "assigned_job": {
                "job_id": "job-999",
                "payload": "work",
                "requirements": {"cpu_cores": 1.0, "ram_gb": 1.0, "gpu_count": 0, "gpu_vram_gb": 0.0},
            }
        }
    )

    monkeypatch.setattr(node_agent.random, "uniform", lambda a, b: 0.1)
    monkeypatch.setattr(node_agent.random, "random", lambda: 1.0)
    monkeypatch.setattr(node_agent.time, "sleep", lambda *_args, **_kwargs: None)

    agent.poll_once()

    assert agent._pending_results[0]["job_id"] == "job-999"
    assert agent._pending_results[0]["success"] is True
