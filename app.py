"""
FastAPI server for the single-flow research frontend.

Endpoints
---------
POST /research                  → start a job, return job_id
GET  /research/{id}             → snapshot (status, events so far, report if done)
GET  /research/{id}/stream      → Server-Sent Events for live updates
GET  /                          → static frontend (served from ./frontend)

Storage
-------
In-memory `jobs` dict holds the live event log for any job currently in flight.
SQLite (./jobs.db) persists (id, question, status, report) once a job completes,
so a shared URL keeps rendering the report after the in-memory job is gc'd.
The SQLite file is on the container's ephemeral disk: it survives in-container
restarts but is wiped on every redeploy.
"""

import asyncio
import json
import logging
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from graph.graph_builder import build_graph
from llm.contract import CITATION_LINK_RE

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = Path("jobs.db")


def init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id           TEXT PRIMARY KEY,
            question     TEXT NOT NULL,
            status       TEXT NOT NULL,
            report       TEXT,
            error        TEXT,
            created_at   TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT
        )
        """
    )
    conn.commit()
    return conn


class Job:
    """In-memory live state for one research run."""

    def __init__(self, question: str):
        self.question: str = question
        self.events: list[dict] = []
        self.status: str = "running"
        self.report: str | None = None
        self.error: str | None = None
        self.started_at: float = time.time()
        self.subscribers: set[asyncio.Queue] = set()

    def append(self, event_name: str, data: dict) -> None:
        # Tag every event with seconds-since-start so the frontend can show
        # per-spirit elapsed times even on resume (no client clock dependency).
        data = {**data, "elapsed_s": round(time.time() - self.started_at, 2)}
        evt = {"id": len(self.events), "event": event_name, "data": data}
        self.events.append(evt)
        for q in list(self.subscribers):
            q.put_nowait(evt)


def _first_line(text: str | None) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    return lines[0] if lines else ""


def build_node_payload(node_name: str, delta: dict) -> dict:
    """Extract per-node data from a state delta, for the spirit detail cards."""
    payload: dict = {"node": node_name, "iteration": delta.get("iteration")}

    if node_name in ("orchestrator", "refiner"):
        payload["queries"] = delta.get("search_queries", []) or []

    elif node_name == "searcher":
        results = delta.get("search_results", []) or []
        payload["results_count"] = len(results)
        payload["urls"] = [r.get("url", "") for r in results]

    elif node_name == "reader":
        sources = delta.get("sources", []) or []
        payload["sources_count"] = len(sources)
        payload["total_raw_kb"] = round(
            sum(s.get("raw_length", 0) for s in sources) / 1024, 1
        )
        payload["sources"] = [
            {"url": s.get("url", ""), "summary_first_line": _first_line(s.get("summary"))}
            for s in sources
        ]

    elif node_name == "critic":
        critique = delta.get("critique") or {}
        payload["passed"] = critique.get("passed")
        payload["feedback"] = critique.get("feedback", "") or ""
        payload["missing_topics"] = critique.get("missing_topics", []) or []

    elif node_name == "writer":
        report = delta.get("final_report") or ""
        payload["word_count"] = len(report.split())
        payload["citation_count"] = len(set(CITATION_LINK_RE.findall(report)))

    return payload


jobs: dict[str, Job] = {}
graph = build_graph()
db: sqlite3.Connection = init_db()


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    db.close()


app = FastAPI(lifespan=lifespan)


class ResearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    max_iterations: int = Field(default=2, ge=1, le=5)


async def run_job(job_id: str, question: str, max_iterations: int) -> None:
    """Run the LangGraph pipeline and publish per-node events to the Job."""
    job = jobs[job_id]
    initial_state = {
        "research_question": question,
        "max_iterations": max_iterations,
        "iteration": 0,
        "search_queries": [],
        "search_results": [],
        "sources": [],
        "critique": None,
        "final_report": None,
        "messages": [],
    }
    try:
        async for step in graph.astream(initial_state):
            # graph.astream yields {node_name: state_delta} after each node finishes
            for node_name, delta in step.items():
                payload = build_node_payload(node_name, delta)
                job.append("node_complete", payload)

                if delta.get("final_report"):
                    job.report = delta["final_report"]

        job.status = "done"
        job.append("complete", {"report": job.report or ""})
        db.execute(
            "INSERT OR REPLACE INTO jobs (id, question, status, report, completed_at) "
            "VALUES (?, ?, 'done', ?, datetime('now'))",
            (job_id, question, job.report or ""),
        )
        db.commit()
    except Exception as exc:
        logger.exception("Job %s failed", job_id)
        job.status = "error"
        job.error = str(exc)
        job.append("error_event", {"message": job.error})
        db.execute(
            "INSERT OR REPLACE INTO jobs (id, question, status, error, completed_at) "
            "VALUES (?, ?, 'error', ?, datetime('now'))",
            (job_id, question, job.error),
        )
        db.commit()


@app.post("/research")
async def start_research(req: ResearchRequest):
    job_id = uuid.uuid4().hex
    jobs[job_id] = Job(req.question)
    asyncio.create_task(run_job(job_id, req.question, req.max_iterations))
    return {"job_id": job_id}


@app.get("/research/{job_id}")
async def snapshot(job_id: str):
    job = jobs.get(job_id)
    if job is not None:
        return {
            "status": job.status,
            "question": job.question,
            "events": job.events,
            "report": job.report,
            "error": job.error,
        }
    row = db.execute(
        "SELECT question, status, report, error FROM jobs WHERE id = ?", (job_id,)
    ).fetchone()
    if row is None:
        return JSONResponse({"error": "expired"}, status_code=404)
    question, status, report, error = row
    return {
        "status": status,
        "question": question,
        "events": [],
        "report": report,
        "error": error,
    }


@app.get("/research/{job_id}/stream")
async def stream(job_id: str, request: Request):
    job = jobs.get(job_id)
    if job is None:
        return JSONResponse({"error": "unknown or expired"}, status_code=404)

    # EventSource can't set headers, so the frontend passes last_event_id as a query param.
    # We also accept the standard Last-Event-ID header for native browser reconnects.
    last_id_str = request.query_params.get(
        "last_event_id", request.headers.get("last-event-id", "-1")
    )
    try:
        last_id = int(last_id_str)
    except ValueError:
        last_id = -1

    async def event_generator():
        # Replay any events the client missed
        for evt in job.events:
            if evt["id"] > last_id:
                yield {
                    "id": str(evt["id"]),
                    "event": evt["event"],
                    "data": json.dumps(evt["data"]),
                }

        if job.status != "running":
            return

        # Subscribe to new events
        q: asyncio.Queue = asyncio.Queue()
        job.subscribers.add(q)
        try:
            while True:
                if await request.is_disconnected():
                    return
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    # sse-starlette sends keepalive pings; this loop also lets us
                    # check is_disconnected periodically.
                    continue
                yield {
                    "id": str(evt["id"]),
                    "event": evt["event"],
                    "data": json.dumps(evt["data"]),
                }
                if evt["event"] in ("complete", "error_event"):
                    return
        finally:
            job.subscribers.discard(q)

    return EventSourceResponse(event_generator())


FRONTEND_DIR = Path(__file__).parent / "frontend"


@app.get("/")
async def index():
    return FileResponse(FRONTEND_DIR / "prototype.html")


@app.get("/r/{job_id}")
async def shareable(job_id: str):
    # Shareable URL: same app, frontend reads /r/{id} and resumes from snapshot.
    return FileResponse(FRONTEND_DIR / "prototype.html")


# Static assets (CSS, JSX). Mounted last; the explicit / and /r/{id} routes
# above take precedence, and the /research/* API routes are already declared.
if FRONTEND_DIR.exists():
    app.mount(
        "/",
        StaticFiles(directory=str(FRONTEND_DIR)),
        name="frontend",
    )
