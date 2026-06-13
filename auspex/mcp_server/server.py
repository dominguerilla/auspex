"""MCP server for Auspex — exposes the research pipeline as MCP tools."""

import asyncio
import logging
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from graph.graph_builder import build_graph

logger = logging.getLogger(__name__)

MAX_ITERATIONS_DEFAULT = 2
MAX_ITERATIONS_CEILING = 5

# Absolute path computed from this file's location so it resolves to
# <project-root>/jobs.db regardless of the working directory at launch.
_DB_PATH = Path(__file__).parent.parent.parent / "jobs.db"

mcp = FastMCP("Auspex Research Agent")

# Build graph once at import time — safe because build_graph() only constructs
# the StateGraph topology; get_llm() is never called until a node actually runs.
_graph = build_graph()

# In-memory job store for this process. Keyed by job_id (uuid4 hex).
_mcp_jobs: dict[str, dict[str, Any]] = {}


# ---------------------------------------------------------------------------
# SQLite helpers (independent of app.py — owns its own connection lifecycle)
# ---------------------------------------------------------------------------

def _get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    """Create the jobs table if absent; idempotent."""
    conn = _get_db()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id             TEXT PRIMARY KEY,
            question       TEXT NOT NULL,
            status         TEXT NOT NULL,
            report         TEXT,
            error          TEXT,
            created_at     TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at   TEXT,
            max_iterations INTEGER,
            duration_ms    INTEGER
        )
        """
    )
    for col, typedef in [("max_iterations", "INTEGER"), ("duration_ms", "INTEGER")]:
        try:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {col} {typedef}")
        except sqlite3.OperationalError:
            pass  # Column already exists (migration from older schema).
    conn.commit()
    conn.close()


def _persist_job(job_id: str, job: dict[str, Any], duration_ms: int) -> None:
    conn = _get_db()
    if job["status"] == "done":
        conn.execute(
            "INSERT OR REPLACE INTO jobs "
            "(id, question, status, report, max_iterations, duration_ms, completed_at) "
            "VALUES (?, ?, 'done', ?, ?, ?, datetime('now'))",
            (job_id, job["question"], job.get("report") or "", job["max_iterations"], duration_ms),
        )
    else:
        conn.execute(
            "INSERT OR REPLACE INTO jobs "
            "(id, question, status, error, max_iterations, duration_ms, completed_at) "
            "VALUES (?, ?, 'error', ?, ?, ?, datetime('now'))",
            (job_id, job["question"], job.get("error"), job["max_iterations"], duration_ms),
        )
    conn.commit()
    conn.close()


def _read_job_from_db(job_id: str) -> dict[str, Any] | None:
    conn = _get_db()
    row = conn.execute(
        "SELECT id, question, status, report, error FROM jobs WHERE id = ?",
        (job_id,),
    ).fetchone()
    conn.close()
    if row is None:
        return None
    return {
        "job_id": row["id"],
        "question": row["question"],
        "status": row["status"],
        "current_node": None,
        "iteration": None,
        "report": row["report"],
        "sources": [],  # sources are never persisted to SQLite
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
        _persist_job(job_id, job, round((time.time() - job["started_at"]) * 1000))
    except Exception as exc:
        logger.exception("MCP job %s failed", job_id)
        job["status"] = "error"
        job["error"] = str(exc)
        _persist_job(job_id, job, round((time.time() - job["started_at"]) * 1000))


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
    db_row = _read_job_from_db(job_id)
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

    Note: sources (scraped web pages) are only available for jobs started in
    the current server session; they are not persisted to the database.

    Args:
        job_id: The job_id returned by start_research.
    """
    job = _mcp_jobs.get(job_id)
    if job is not None:
        return {
            "job_id": job_id,
            "status": job["status"],
            "report": job["report"],
            "sources": job["sources"],
        }
    db_row = _read_job_from_db(job_id)
    if db_row is None:
        raise ValueError(f"Unknown job_id: {job_id!r}")
    return {
        "job_id": job_id,
        "status": db_row["status"],
        "report": db_row["report"],
        "sources": [],  # never persisted; empty for DB-restored jobs
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
    db_row = _read_job_from_db(job_id)
    if db_row is None:
        raise ValueError(f"Unknown job_id: {job_id!r}")
    if db_row["status"] != "done" or not db_row["report"]:
        raise ValueError(
            f"Job {job_id!r} is not done yet (status: {db_row['status']!r}). "
            "Call get_research_status to check progress."
        )
    return db_row["report"]


# Create the DB table on first import (idempotent).
_init_db()
