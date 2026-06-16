"""MCP server for Auspex — exposes the research pipeline as MCP tools."""

import asyncio
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

mcp = FastMCP("Auspex Research Agent")

# Build graph once at import time — safe because build_graph() only constructs
# the StateGraph topology; get_llm() is never called until a node actually runs.
_graph = build_graph()

# In-memory job store for this process. Keyed by job_id (uuid4 hex).
_mcp_jobs: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# Postgres helpers (schema is owned by Alembic — see alembic/, docs/adr/0004)
# ---------------------------------------------------------------------------

def _get_db():
    """Open a new psycopg2 connection with dict-style rows.

    psycopg2 is used (not psycopg3) because psycopg3's bundled libpq conflicts
    with the langchain/langgraph native stack in-process on Windows, crashing
    on connect (see docs/adr/0004). psycopg2's `with conn` commits/rolls back
    but does NOT close, so callers close in a finally.
    """
    return psycopg2.connect(_DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def _agent_model_name() -> str:
    """Provider/model that produced a report, for eval attribution (see 0003).

    Mirrors evals/adapter so a stored run stays attributable to its model.
    """
    info = describe_llm()
    return f"{info['provider']}/{info['model'] or 'unknown'}"


def _persist_job(job_id: str, job: dict[str, Any], duration_ms: int) -> None:
    """Upsert the job row and replace its sources. Called once at job end."""
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
    """Read a persisted job and its durable sources, or None if unknown."""
    conn = _get_db()
    try:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, question, status, report, error FROM jobs WHERE id = %s",
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
        "current_node": None,
        "iteration": None,
        "report": row["report"],
        "sources": sources,
        "error": row["error"],
    }


# ---------------------------------------------------------------------------
# Background job runner
# ---------------------------------------------------------------------------

async def _run_job(job_id: str) -> None:
    job = _mcp_jobs[job_id]
    job["status"] = "running"
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
    try:
        async for step in _graph.astream(initial_state):
            for node_name, delta in step.items():
                job["current_node"] = node_name
                # iteration is only set by the critic node; avoid overwriting with None
                if delta.get("iteration") is not None:
                    job["iteration"] = delta["iteration"]
                # sources come from the reader node; capture while they're in-memory
                if node_name == "reader" and delta.get("sources"):
                    job["sources"] = delta["sources"]
                if delta.get("final_report"):
                    job["report"] = delta["final_report"]
        job["status"] = "done"
        await asyncio.to_thread(
            _persist_job, job_id, job, round((time.time() - job["started_at"]) * 1000)
        )
    except Exception as exc:
        logger.exception("MCP job %s failed", job_id)
        job["status"] = "error"
        job["error"] = str(exc)
        await asyncio.to_thread(
            _persist_job, job_id, job, round((time.time() - job["started_at"]) * 1000)
        )


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
    _mcp_jobs[job_id] = {
        "job_id": job_id,
        "question": query,
        "status": "queued",
        "current_node": None,
        "iteration": None,
        "report": None,
        "sources": [],
        "error": None,
        "max_iterations": max_iterations,
        "agent_model": _agent_model_name(),
        "started_at": time.time(),
    }
    asyncio.create_task(_run_job(job_id))
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
    job = _mcp_jobs.get(job_id)
    if job is not None:
        return {
            "job_id": job_id,
            "status": job["status"],
            "current_node": job["current_node"],
            "iteration": job["iteration"],
            "error": job["error"],
        }
    db_row = await asyncio.to_thread(_read_job_from_db, job_id)
    if db_row is None:
        raise ValueError(f"Unknown job_id: {job_id!r}")
    return {
        "job_id": job_id,
        "status": db_row["status"],
        "current_node": None,
        "iteration": None,
        "error": db_row["error"],
    }


@mcp.tool()
async def get_research_report(job_id: str) -> dict:
    """Retrieve the completed research report for a job.

    Returns a dict with keys: job_id, status, report, sources.

    If status is not 'done', report is None — keep polling get_research_status
    and retry once it transitions to 'done'.

    Sources (scraped web pages) are persisted durably, so they are returned
    whether the job is still in memory or restored from the database.

    Args:
        job_id: The job_id returned by start_research.
    """
    job = _mcp_jobs.get(job_id)
    if job is not None:
        response = {
            "job_id": job_id,
            "status": job["status"],
            "report": job["report"],
            "sources": job["sources"],
        }
        # Once a terminal job's report has been retrieved, drop it from the
        # in-memory store to bound memory use. Status, report, and sources all
        # remain available via the Postgres fallback below.
        if job["status"] in ("done", "error"):
            _mcp_jobs.pop(job_id, None)
        return response
    db_row = await asyncio.to_thread(_read_job_from_db, job_id)
    if db_row is None:
        raise ValueError(f"Unknown job_id: {job_id!r}")
    return {
        "job_id": job_id,
        "status": db_row["status"],
        "report": db_row["report"],
        "sources": db_row["sources"],
    }


# ---------------------------------------------------------------------------
# MCP resource
# ---------------------------------------------------------------------------

@mcp.resource("research://{job_id}")
async def research_report_resource(job_id: str) -> str:
    """Return the raw Markdown report for a completed research job."""
    job = _mcp_jobs.get(job_id)
    if job is not None and job["status"] == "done" and job["report"]:
        return job["report"]
    db_row = await asyncio.to_thread(_read_job_from_db, job_id)
    if db_row is None:
        raise ValueError(f"Unknown job_id: {job_id!r}")
    if db_row["status"] != "done" or not db_row["report"]:
        raise ValueError(
            f"Job {job_id!r} is not done yet (status: {db_row['status']!r}). "
            "Call get_research_status to check progress."
        )
    return db_row["report"]


# ---------------------------------------------------------------------------
# HTTP transport (remote MCP clients on the LAN)
# ---------------------------------------------------------------------------

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

    Disables FastMCP's localhost-only DNS-rebinding protection (which it
    auto-enables when constructed with the default host=127.0.0.1) so that
    LAN clients are not rejected with 421 Misdirected Request. When ``token``
    is provided, every HTTP request must carry ``Authorization: Bearer <token>``.
    """
    mcp.settings.transport_security = None
    app = mcp.streamable_http_app()
    if token:
        app = BearerAuthMiddleware(app, token)
    return app


# Schema is managed by Alembic migrations (see alembic/, docs/adr/0004) —
# run `alembic upgrade head` against DATABASE_URL before serving.
