"""
EdgeCompute Orchestrator (FastAPI).

Implements the pull-based, NAT-friendly control plane:
  - Node Agents register once, then POLL for work on an interval.
  - The orchestrator NEVER opens an outbound connection back to a node —
    this is what makes volunteer PCs behind home routers usable without
    port forwarding or a relay.
  - Each poll both reports resource availability AND returns completed
    job results, so a single round trip does double duty.

Run with:  uvicorn orchestrator.main:app --reload --port 8000
"""
from __future__ import annotations

import time

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

from .ledger import compute_payout
from .logging_config import configure_json_logging, get_logger
from .models import (
    AssignedJob,
    HealthResponse,
    Job,
    JobResult,
    JobStatus,
    JobSubmitRequest,
    JobSubmitResponse,
    Node,
    NodeRegisterRequest,
    NodeRegisterResponse,
    PollRequest,
    PollResponse,
)
from .reliability import update_on_job_result, update_on_missed_poll
from .scheduler import select_node
from .state import STORE

configure_json_logging()
log = get_logger("edgecompute.orchestrator")

app = FastAPI(title="EdgeCompute Orchestrator", version="0.1.0")

DEFAULT_STRATEGY = "hybrid"

# Prometheus metrics
JOB_SUBMITTED = Counter("edgecompute_jobs_submitted_total", "Total submitted jobs")
JOB_COMPLETED = Counter("edgecompute_jobs_completed_total", "Total completed jobs")
JOB_FAILED = Counter("edgecompute_jobs_failed_total", "Total failed jobs")
JOB_RUNTIME_SECONDS = Histogram("edgecompute_job_runtime_seconds", "Job runtime seconds")

@app.post("/nodes/register", response_model=NodeRegisterResponse)
def register_node(req: NodeRegisterRequest) -> NodeRegisterResponse:
    node = Node(
        tier=req.tier,
        resources=req.resources,
        region=req.region,
        lat=req.lat,
        lon=req.lon,
        energy_cost_per_kwh=req.energy_cost_per_kwh,
    )
    STORE.register_node(node)
    log.info(
        "node registered",
        extra={"node_id": node.node_id, "tier": int(node.tier), "region": node.region},
    )
    return NodeRegisterResponse(node_id=node.node_id)


@app.post("/nodes/{node_id}/poll", response_model=PollResponse)
def poll(node_id: str, req: PollRequest) -> PollResponse:
    node = STORE.touch_node(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="unknown node_id — register first")

    node.resources = req.available_resources

    # 1. fold in any completed job results (updates EWMA + pays credits)
    for result in req.completed_results:
        _handle_job_result(node, result)

    # 2. if this node is currently idle, try to hand it the next job
    assigned = None
    if node.current_job_id is None:
        job = STORE.pop_next_assignable()
        if job is not None:
            chosen = select_node(job, [node], strategy=DEFAULT_STRATEGY)
            if chosen is not None:
                job.status = JobStatus.ASSIGNED
                job.assigned_node_id = node.node_id
                job.assigned_at = time.time()
                node.current_job_id = job.job_id
                assigned = AssignedJob(
                    job_id=job.job_id, payload=job.payload, requirements=job.requirements,
                )
                log.info(
                    "job assigned",
                    extra={"job_id": job.job_id, "node_id": node.node_id},
                )
            else:
                STORE.requeue(job)  # didn't fit this node after all; put back

    return PollResponse(assigned_job=assigned, credit_balance=node.credit_balance)


def _handle_job_result(node: Node, result: JobResult) -> None:
    job = STORE.get_job(result.job_id)
    if job is None:
        log.warning(
            "result for unknown job",
            extra={"job_id": result.job_id, "node_id": node.node_id},
        )
        return

    job.result = result
    job.completed_at = time.time()
    job.status = JobStatus.COMPLETED if result.success else JobStatus.FAILED
    node.current_job_id = None

    node.reliability_score = update_on_job_result(
        node.reliability_score, success=result.success, latency_ms=result.latency_ms,
    )

    if result.success and job.assigned_at is not None:
        runtime_seconds = job.completed_at - job.assigned_at
        payout = compute_payout(job.requirements, runtime_seconds, node.reliability_score)
        node.credit_balance += payout
        log.info(
            "job completed",
            extra={
                "job_id": job.job_id, "node_id": node.node_id,
                "runtime_seconds": round(runtime_seconds, 3), "payout": round(payout, 4),
            },
        )
        try:
            JOB_RUNTIME_SECONDS.observe(runtime_seconds)
        except Exception:
            log.exception("failed to record job runtime metric")
        JOB_COMPLETED.inc()
    elif not result.success:
        log.info(
            "job failed, requeueing",
            extra={"job_id": job.job_id, "node_id": node.node_id},
        )
        STORE.requeue(job)
        JOB_FAILED.inc()


@app.post("/jobs", response_model=JobSubmitResponse)
def submit_job(req: JobSubmitRequest) -> JobSubmitResponse:
    job = Job(
        payload=req.payload,
        requirements=req.requirements,
        origin_lat=req.origin_lat,
        origin_lon=req.origin_lon,
    )
    STORE.submit_job(job)
    JOB_SUBMITTED.inc()
    log.info(
        "job queued",
        extra={
            "job_id": job.job_id, "cpu_cores": req.requirements.cpu_cores,
            "ram_gb": req.requirements.ram_gb, "gpu_count": req.requirements.gpu_count,
        },
    )
    return JobSubmitResponse(job_id=job.job_id, status=job.status)


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    job = STORE.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job_id")
    return job


@app.get("/nodes")
def list_nodes():
    """Debug/dashboard endpoint: current view of the resource pool."""
    active_ids = {n.node_id for n in STORE.active_nodes()}
    return [
        {**n.model_dump(), "online": n.node_id in active_ids}
        for n in STORE.nodes.values()
    ]


@app.get("/health", response_model=HealthResponse, tags=["health"], summary="Health check")
def health() -> HealthResponse:
    """Liveness/readiness probe: reports orchestrator status and pool size."""
    return HealthResponse(
        status="ok",
        active_nodes=len(STORE.active_nodes()),
        queued_jobs=len(STORE.queue),
    )


@app.get("/healthz", response_model=HealthResponse, tags=["health"], summary="Health check (alias)")
def healthz() -> HealthResponse:
    """Alias of /health for infrastructure that expects the /healthz convention."""
    return health()


@app.get("/metrics")
def metrics() -> Response:
    """Prometheus metrics endpoint."""
    try:
        data = generate_latest()
        return Response(content=data, media_type=CONTENT_TYPE_LATEST)
    except Exception:
        # metrics endpoint must not crash the app
        return Response(content=b"", media_type=CONTENT_TYPE_LATEST)


def reap_stale_nodes() -> None:
    """
    Call periodically (e.g. from a background task or cron) to penalize
    nodes that stopped polling without explaining why — this is the
    'missed poll' half of the EWMA reliability model. Any job left
    assigned to a now-stale node is requeued.
    """
    for node in STORE.stale_nodes():
        node.reliability_score = update_on_missed_poll(node.reliability_score)
        if node.current_job_id:
            job = STORE.get_job(node.current_job_id)
            if job and job.status in (JobStatus.ASSIGNED, JobStatus.RUNNING):
                log.info(
                    "node went stale mid-job, requeueing",
                    extra={"node_id": node.node_id, "job_id": job.job_id},
                )
                STORE.requeue(job)
            node.current_job_id = None
