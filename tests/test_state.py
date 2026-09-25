"""State store tests for queue and staleness behavior."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from orchestrator.models import Job, JobStatus, Node, ResourceProfile, Tier  # noqa: E402
from orchestrator.state import Store  # noqa: E402


def _make_job(payload: str = "job", *, status: JobStatus = JobStatus.QUEUED) -> Job:
    return Job(
        payload=payload,
        requirements=ResourceProfile(cpu_cores=2.0, ram_gb=4.0, gpu_count=0),
        status=status,
    )


def test_store_pop_next_assignable_returns_oldest_queued_job():
    store = Store()
    first = _make_job("first")
    second = _make_job("second")

    store.submit_job(first)
    store.submit_job(second)

    popped = store.pop_next_assignable()
    assert popped is not None
    assert popped.job_id == first.job_id
    assert store.queue == [second.job_id]


def test_pop_next_assignable_skips_non_queued_jobs():
    store = Store()
    finished = _make_job("finished", status=JobStatus.COMPLETED)
    queued = _make_job("queued")

    store.jobs[finished.job_id] = finished
    store.jobs[queued.job_id] = queued
    store.queue = [finished.job_id, queued.job_id]

    popped = store.pop_next_assignable()
    assert popped is not None
    assert popped.job_id == queued.job_id
    assert store.queue == [finished.job_id]


def test_requeue_places_job_at_front_of_queue_and_clears_assignment():
    store = Store()
    job = _make_job("retry")
    job.status = JobStatus.ASSIGNED
    job.assigned_node_id = "node-42"
    store.submit_job(job)

    store.requeue(job)

    assert job.status == JobStatus.QUEUED
    assert job.assigned_node_id is None
    assert store.queue[0] == job.job_id


def test_touch_node_updates_last_seen_timestamp():
    store = Store()
    node = Node(tier=Tier.VOLUNTEER, resources=ResourceProfile(cpu_cores=4.0, ram_gb=8.0), region="test")
    store.register_node(node)

    old_seen = node.last_seen
    time.sleep(0.02)
    updated = store.touch_node(node.node_id)

    assert updated is not None
    assert updated.last_seen >= old_seen


def test_active_nodes_ignores_stale_nodes():
    store = Store()
    fresh = Node(
        tier=Tier.VOLUNTEER,
        resources=ResourceProfile(cpu_cores=2.0, ram_gb=4.0),
        region="fresh",
        last_seen=time.time(),
    )
    stale = Node(
        tier=Tier.VOLUNTEER,
        resources=ResourceProfile(cpu_cores=2.0, ram_gb=4.0),
        region="stale",
        last_seen=time.time() - 60.0,
    )
    store.register_node(fresh)
    store.register_node(stale)

    active_ids = {node.node_id for node in store.active_nodes()}
    stale_ids = {node.node_id for node in store.stale_nodes()}

    assert fresh.node_id in active_ids
    assert stale.node_id in stale_ids
    assert stale.node_id not in active_ids


def test_stale_nodes_detects_nodes_older_than_timeout():
    store = Store()
    node = Node(
        tier=Tier.VOLUNTEER,
        resources=ResourceProfile(cpu_cores=1.0, ram_gb=2.0),
        region="late",
        last_seen=time.time() - 21.0,
    )
    store.register_node(node)

    stale = store.stale_nodes()
    assert [n.node_id for n in stale] == [node.node_id]
