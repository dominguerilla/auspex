"""MCP server for Auspex — exposes the research pipeline as MCP tools.

Job execution is split from request handling (see docs/adr/0005): a job is
persisted to Postgres the moment it is created, and the research runs in a
separate request. In the hosted (Cloud Run) deployment that request is delivered
by **Cloud Tasks** to the ``/internal/run-job`` route; for local/stdio dev (no
Cloud Tasks configured) it falls back to an in-process background task. Either
way, all job state lives in Postgres, so status/report reads work from any
instance and survive scale-to-zero.
"""

import asyncio
import json
import logging
import os
import secrets
import time
import uuid
from typing import Any

import psycopg2
import psycopg2.extras
from mcp.server.fastmcp import FastMCP
from starlette.responses import JSONResponse
from starlette.routing import Route

from graph.graph_builder import build_graph
from llm.ollama_client import describe_llm

logger = logging.getLogger(__name__)

MAX_ITERATIONS_DEFAULT = 2
MAX_ITERATIONS_CEILING = 5

# Postgres connection string. Defaults to the local docker-compose database;
# override with DATABASE_URL in any hosted environment (see docs/adr/0004).
_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://auspex:auspex@localhost:5432/auspex"
)

# Cloud Tasks dispatch (see docs/adr/0005). When all four are set, start_research
# enqueues the job onto a Cloud Tasks queue that POSTs to WORKER_BASE_URL +
# /internal/run-job; otherwise it runs the job in-process (local/stdio dev).
_GCP_PROJECT = os.environ.get("GCP_PROJECT")
_TASKS_LOCATION = os.environ.get("CLOUD_TASKS_LOCATION")
_TASKS_QUEUE = os.environ.get("CLOUD_TASKS_QUEUE")
_WORKER_BASE_URL = os.environ.get("WORKER_BASE_URL")
_MCP_TOKEN = os.environ.get("AUSPEX_MCP_TOKEN")

mcp = FastMCP("Auspex Research Agent")

# Build graph once at import time — safe because build_graph() only constructs
# the StateGraph topology; get_llm() is never called until a node actually runs.
_graph = build_graph()


def _cloud_tasks_enabled() -> bool:
    """True if a Cloud Tasks queue is fully configured for durable dispatch."""
    return all((_GCP_PROJECT, _TASKS_LOCATION, _TASKS_QUEUE, _WORKER_BASE_URL))


# ---------------------------------------------------------------------------
# Postgres helpers (schema is owned by Alembic — see alembic/, docs/adr/0004)
# ---------------------------------------------------------------------------

def _get_db():
    """Open a new psycopg2 connection with dict-style rows.

    psycopg2 is used (not psycopg3) because psycopg3's bundled libpq conflicts
    with the langchain/langgraph native stack in-process on Windows, crashing
    on connect (see docs/adr/0004).
    """
    return psycopg2.connect(_DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def _agent_model_name() -> str:
    """Provider/model that produced a report, for eval attribution (see 0003)."""
    info = describe_llm()
    return f"{info['provider']}/{info['model'] or 'unknown'}"


def _create_job(job_id: str, question: str, max_iterations: int, agent_model: str) -> None:
    """Insert a fresh job row in the 'queued' state (see docs/adr/0005)."""
    conn = _get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO jobs (id, question, status, max_iterations, agent_model) "
                "VALUES (%s, %s, 'queued', %s, %s)",
                (job_id, question, max_iterations, agent_model),
            )
        conn.commit()
    finally:
        conn.close()


def _set_job_running(job_id: str) -> None:
    """Transition a job to 'running' (the worker calls this when it picks it up)."""
    conn = _get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE jobs SET status = 'running' WHERE id = %s", (job_id,))
        conn.commit()
    finally:
        conn.close()


def _set_job_progress(job_id: str, current_node: str, iteration: int | None) -> None:
    """Record live progress (active node + iteration) so status reflects it."""
    conn = _get_db()
    try:
        with conn.cursor() as cur:
            if iteration is not None:
                cur.execute(
                    "UPDATE jobs SET current_node = %s, iteration = %s WHERE id = %s",
                    (current_node, iteration, job_id),
                )
            else:
                cur.execute(
                    "UPDATE jobs SET current_node = %s WHERE id = %s",
                    (current_node, job_id),
                )
        conn.commit()
    finally:
        conn.close()


def _persist_job(job_id: str, job: dict[str, Any], duration_ms: int) -> None:
    """Upsert the terminal job row and replace its sources. Called at job end."""
    conn = _get_db()
    try:
        cur = conn.cursor()
        if job["status"] == "done":
            cur.execute(
                """
                INSERT INTO jobs (id, question, status, report, max_iterations,
                                  duration_ms, agent_model, completed_at)
                VALUES (%s, %s, 'done', %s, %s, %s, %s, now())
                ON CONFLICT (id) DO UPDATE SET
                    status         = EXCLUDED.status,
                    report         = EXCLUDED.report,
                    max_iterations = EXCLUDED.max_iterations,
                    duration_ms    = EXCLUDED.duration_ms,
                    agent_model    = EXCLUDED.agent_model,
                    completed_at   = EXCLUDED.completed_at
                """,
                (job_id, job["question"], job.get("report") or "",
                 job["max_iterations"], duration_ms, job.get("agent_model")),
            )
        else:
            cur.execute(
                """
                INSERT INTO jobs (id, question, status, error, max_iterations,
                                  duration_ms, agent_model, completed_at)
                VALUES (%s, %s, 'error', %s, %s, %s, %s, now())
                ON CONFLICT (id) DO UPDATE SET
                    status         = EXCLUDED.status,
                    error          = EXCLUDED.error,
                    max_iterations = EXCLUDED.max_iterations,
                    duration_ms    = EXCLUDED.duration_ms,
                    agent_model    = EXCLUDED.agent_model,
                    completed_at   = EXCLUDED.completed_at
                """,
                (job_id, job["question"], job.get("error"),
                 job["max_iterations"], duration_ms, job.get("agent_model")),
            )
        # Replace any existing sources for this job (idempotent re-persist).
        cur.execute("DELETE FROM sources WHERE job_id = %s", (job_id,))
        sources = job.get("sources") or []
        if sources:
            cur.executemany(
                "INSERT INTO sources (job_id, url, summary, raw_length) "
                "VALUES (%s, %s, %s, %s)",
                [
                    (job_id, s.get("url"), s.get("summary") or "", s.get("raw_length") or 0)
                    for s in sources
                ],
            )
        conn.commit()
    finally:
        conn.close()


def _read_job_from_db(job_id: str) -> dict[str, Any] | None:
    """Read a job and its durable sources, or None if the id is unknown."""
    conn = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, question, status, report, error, current_node, iteration, "
            "max_iterations, agent_model FROM jobs WHERE id = %s",
            (job_id,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        cur.execute(
            "SELECT url, summary, raw_length FROM sources WHERE job_id = %s ORDER BY id",
            (job_id,),
        )
        sources = [dict(s) for s in cur.fetchall()]
    finally:
        conn.close()
    return {
        "job_id": row["id"],
        "question": row["question"],
        "status": row["status"],
        "current_node": row["current_node"],
        "iteration": row["iteration"],
        "report": row["report"],
        "sources": sources,
        "error": row["error"],
        "max_iterations": row["max_iterations"],
        "agent_model": row["agent_model"],
    }


# ---------------------------------------------------------------------------
# Job runner (invoked by the Cloud Tasks worker route, or in-process for dev)
# ---------------------------------------------------------------------------

async def _run_job_from_db(job_id: str) -> None:
    """Load a queued job from Postgres, run the pipeline, persist the result.

    Idempotent enough for at-least-once delivery: Cloud Tasks may retry, and a
    re-run simply re-executes the pipeline and re-upserts the row.
    """
    row = await asyncio.to_thread(_read_job_from_db, job_id)
    if row is None:
        logger.error("run-job: unknown job_id %r — nothing to run", job_id)
        return

    started_at = time.time()
    await asyncio.to_thread(_set_job_running, job_id)
    job: dict[str, Any] = {
        "question": row["question"],
        "max_iterations": row["max_iterations"],
        "agent_model": row["agent_model"],
        "status": "running",
        "report": None,
        "sources": [],
        "error": None,
    }
    initial_state = {
        "research_question": job["question"],
        "max_iterations": job["max_iterations"],
        "iteration": 0,
        "search_queries": [],
        "search_results": [],
        "sources": [],
        "critique": None,
        "final_report": None,
        "messages": [],
    }
    iteration: int | None = None
    try:
        async for step in _graph.astream(initial_state):
            for node_name, delta in step.items():
                # iteration is only set by the critic node; don't overwrite with None
                if delta.get("iteration") is not None:
                    iteration = delta["iteration"]
                # sources come from the reader node; capture while in-memory
                if node_name == "reader" and delta.get("sources"):
                    job["sources"] = delta["sources"]
                if delta.get("final_report"):
                    job["report"] = delta["final_report"]
                await asyncio.to_thread(_set_job_progress, job_id, node_name, iteration)
        job["status"] = "done"
        await asyncio.to_thread(
            _persist_job, job_id, job, round((time.time() - started_at) * 1000)
        )
    except Exception as exc:
        logger.exception("MCP job %s failed", job_id)
        job["status"] = "error"
        job["error"] = str(exc)
        await asyncio.to_thread(
            _persist_job, job_id, job, round((time.time() - started_at) * 1000)
        )


def _enqueue_cloud_task(job_id: str) -> None:
    """Enqueue a Cloud Tasks task that POSTs {job_id} to the worker route."""
    from google.cloud import tasks_v2

    client = tasks_v2.CloudTasksClient()
    parent = client.queue_path(_GCP_PROJECT, _TASKS_LOCATION, _TASKS_QUEUE)
    headers = {"Content-Type": "application/json"}
    if _MCP_TOKEN:
        headers["Authorization"] = f"Bearer {_MCP_TOKEN}"
    task = {
        "http_request": {
            "http_method": tasks_v2.HttpMethod.POST,
            "url": f"{_WORKER_BASE_URL}/internal/run-job",
            "headers": headers,
            "body": json.dumps({"job_id": job_id}).encode(),
        }
    }
    client.create_task(parent=parent, task=task)


async def _dispatch_job(job_id: str) -> None:
    """Hand the job to Cloud Tasks (hosted) or run it in-process (local dev)."""
    if _cloud_tasks_enabled():
        await asyncio.to_thread(_enqueue_cloud_task, job_id)
    else:
        asyncio.create_task(_run_job_from_db(job_id))


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------

@mcp.tool()
async def start_research(query: str, max_iterations: int | None = None) -> dict:
    """Start a background research job. Returns immediately with a job_id.

    Poll get_research_status with the returned job_id to track progress.
    Call get_research_report once status is 'done' to read the full report.

    Args:
        query: The research question (required, non-empty).
        max_iterations: Max critique/refine cycles (1–5, default 2). Higher
            values produce more thorough research but take longer.
    """
    query = query.strip()
    if not query:
        raise ValueError("query must not be empty")
    if max_iterations is None:
        max_iterations = MAX_ITERATIONS_DEFAULT
    max_iterations = max(1, min(max_iterations, MAX_ITERATIONS_CEILING))

    job_id = uuid.uuid4().hex
    await asyncio.to_thread(
        _create_job, job_id, query, max_iterations, _agent_model_name()
    )
    await _dispatch_job(job_id)
    return {"job_id": job_id, "status": "queued"}


@mcp.tool()
async def get_research_status(job_id: str) -> dict:
    """Get the current status of a research job.

    Returns a dict with keys: job_id, status, current_node, iteration, error.

    Status values:
    - "queued"  — job accepted, not yet started
    - "running" — pipeline is executing; current_node shows the active step
    - "done"    — research complete; call get_research_report for the report
    - "error"   — pipeline failed; error field contains the exception message

    Args:
        job_id: The job_id returned by start_research.
    """
    row = await asyncio.to_thread(_read_job_from_db, job_id)
    if row is None:
        raise ValueError(f"Unknown job_id: {job_id!r}")
    return {
        "job_id": job_id,
        "status": row["status"],
        "current_node": row["current_node"],
        "iteration": row["iteration"],
        "error": row["error"],
    }


@mcp.tool()
async def get_research_report(job_id: str) -> dict:
    """Retrieve the completed research report for a job.

    Returns a dict with keys: job_id, status, report, sources.

    If status is not 'done', report is None — keep polling get_research_status
    and retry once it transitions to 'done'. Sources (scraped web pages) are
    persisted durably and returned with the report.

    Args:
        job_id: The job_id returned by start_research.
    """
    row = await asyncio.to_thread(_read_job_from_db, job_id)
    if row is None:
        raise ValueError(f"Unknown job_id: {job_id!r}")
    return {
        "job_id": job_id,
        "status": row["status"],
        "report": row["report"],
        "sources": row["sources"],
    }


# ---------------------------------------------------------------------------
# MCP resource
# ---------------------------------------------------------------------------

@mcp.resource("research://{job_id}")
async def research_report_resource(job_id: str) -> str:
    """Return the raw Markdown report for a completed research job."""
    row = await asyncio.to_thread(_read_job_from_db, job_id)
    if row is None:
        raise ValueError(f"Unknown job_id: {job_id!r}")
    if row["status"] != "done" or not row["report"]:
        raise ValueError(
            f"Job {job_id!r} is not done yet (status: {row['status']!r}). "
            "Call get_research_status to check progress."
        )
    return row["report"]


# ---------------------------------------------------------------------------
# HTTP transport (remote MCP clients + the Cloud Tasks worker route)
# ---------------------------------------------------------------------------

async def run_job_endpoint(request):
    """Cloud Tasks target: run the job named in the POST body to completion.

    Runs synchronously within the request so Cloud Run keeps the instance (and
    CPU) alive for the job's full duration (see docs/adr/0005). Protected by the
    same bearer token as the MCP endpoint (Cloud Tasks attaches it).
    """
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    job_id = (payload or {}).get("job_id")
    if not job_id:
        return JSONResponse({"error": "job_id is required"}, status_code=400)
    await _run_job_from_db(job_id)
    return JSONResponse({"job_id": job_id, "status": "processed"})


class BearerAuthMiddleware:
    """Pure-ASGI middleware enforcing a static bearer token on HTTP requests.

    Implemented at the ASGI layer (not Starlette's BaseHTTPMiddleware) so it
    does not buffer or interfere with the streamable-HTTP transport's
    long-lived responses. Non-HTTP scopes (lifespan, websocket) pass through
    untouched so the inner app's startup/shutdown still runs.
    """

    def __init__(self, app, token: str):
        self._app = app
        self._expected = f"Bearer {token}"

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        provided = headers.get(b"authorization", b"").decode("latin-1")
        if not secrets.compare_digest(provided, self._expected):
            await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
            return
        await self._app(scope, receive, send)


def build_http_app(token: str | None = None):
    """Build the streamable-HTTP ASGI app for the MCP server.

    Adds the ``/internal/run-job`` worker route (Cloud Tasks target) and
    disables FastMCP's localhost-only DNS-rebinding protection so LAN/Cloud Run
    clients are not rejected with 421. When ``token`` is provided, every HTTP
    request — MCP and the worker route alike — must carry
    ``Authorization: Bearer <token>``.
    """
    mcp.settings.transport_security = None
    app = mcp.streamable_http_app()
    app.router.routes.append(
        Route("/internal/run-job", run_job_endpoint, methods=["POST"])
    )
    if token:
        app = BearerAuthMiddleware(app, token)
    return app


# Schema is managed by Alembic migrations (see alembic/, docs/adr/0004, 0005) —
# run `alembic upgrade head` against DATABASE_URL before serving.
