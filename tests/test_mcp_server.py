"""Unit tests for the Auspex MCP server.

The pipeline (``_graph``) is mocked so no LLM calls or network access occur.
Job state lives in Postgres from creation (the worker split, docs/adr/0005), so
these tests require a reachable database (``DATABASE_URL``, default the local
docker-compose Postgres) and are skipped if none is available. CI provides one.
"""

import asyncio
import os
import time
from unittest.mock import MagicMock

import psycopg2
import pytest
import pytest_asyncio

TEST_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://auspex:auspex@localhost:5432/auspex"
)


def _connect():
    return psycopg2.connect(TEST_DATABASE_URL, connect_timeout=3)


def _schema_ready() -> bool:
    """True if Postgres is reachable AND the jobs/sources schema exists."""
    try:
        conn = _connect()
    except Exception:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.jobs'), to_regclass('public.sources')")
            jobs, sources = cur.fetchone()
            # current_node was added in migration 0002 — guard against a stale schema.
            cur.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'jobs' AND column_name = 'current_node'"
            )
            has_progress = cur.fetchone() is not None
        return jobs is not None and sources is not None and has_progress
    except Exception:
        return False
    finally:
        conn.close()


pytestmark = pytest.mark.skipif(
    not _schema_ready(),
    reason="Postgres not reachable or not migrated (run `alembic upgrade head`)",
)


# ---------------------------------------------------------------------------
# Mock graph
# ---------------------------------------------------------------------------

HAPPY_PATH_STEPS = [
    {"orchestrator": {"search_queries": ["quantum computing overview"], "iteration": None}},
    {
        "searcher": {
            "search_results": [
                {"url": "http://example.com/a", "title": "QC intro", "snippet": "snip"}
            ],
            "iteration": None,
        }
    },
    {
        "reader": {
            "sources": [
                {"url": "http://example.com/a", "summary": "Summary A", "raw_length": 800}
            ],
            "iteration": None,
        }
    },
    {
        "critic": {
            "critique": {"passed": True, "feedback": "Good coverage.", "missing_topics": []},
            "iteration": 1,
        }
    },
    {"writer": {"final_report": "# Research Report\n\nContent here.", "iteration": None}},
]


def make_mock_graph(steps: list[dict]):
    """Return a mock compiled graph whose astream() yields the given steps."""

    async def fake_astream(initial_state):
        for step in steps:
            yield step

    mock = MagicMock()
    mock.astream = fake_astream
    return mock


def make_failing_graph(exc: Exception):
    async def fake_astream(initial_state):
        raise exc
        yield  # make it a generator

    mock = MagicMock()
    mock.astream = fake_astream
    return mock


async def _async_noop(*args, **kwargs):
    """Stand-in for _dispatch_job so a job stays 'queued' for inspection."""
    return None


class _FakeRequest:
    """Minimal stand-in for a Starlette Request with a JSON body."""

    def __init__(self, payload):
        self._payload = payload

    async def json(self):
        return self._payload


# ---------------------------------------------------------------------------
# Postgres fixtures
# ---------------------------------------------------------------------------


def _truncate() -> None:
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("TRUNCATE sources, jobs RESTART IDENTITY CASCADE")
        conn.commit()
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _clean_db():
    """Empty the job/source tables before and after each test."""
    _truncate()
    yield
    _truncate()


def _seed_job(job_id, *, question="q", status="done", report=None, error=None, sources=None):
    """Insert a job row (and optional sources) directly into Postgres."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO jobs (id, question, status, report, error) VALUES (%s, %s, %s, %s, %s)",
                (job_id, question, status, report, error),
            )
            for s in sources or []:
                cur.execute(
                    "INSERT INTO sources (job_id, url, summary, raw_length) VALUES (%s, %s, %s, %s)",
                    (job_id, s["url"], s["summary"], s["raw_length"]),
                )
        conn.commit()
    finally:
        conn.close()


def _db_job(job_id):
    """Read a job row back as a dict, or None."""
    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, report, error, current_node, iteration, max_iterations, "
                "agent_model FROM jobs WHERE id = %s",
                (job_id,),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    keys = ["status", "report", "error", "current_node", "iteration", "max_iterations",
            "agent_model"]
    return dict(zip(keys, row))


async def _await_status(srv, job_id, target, timeout=3.0):
    """Poll get_research_status until it reaches `target` (or times out)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = await srv.get_research_status(job_id)
        if status["status"] == target:
            return status
        await asyncio.sleep(0.02)
    return await srv.get_research_status(job_id)


@pytest_asyncio.fixture
async def patched_server(monkeypatch):
    """MCP server module with _graph mocked, the test DB wired in, and Cloud
    Tasks disabled (so start_research dispatches in-process)."""
    import auspex.mcp_server.server as srv

    monkeypatch.setattr(srv, "_DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setattr(srv, "_graph", make_mock_graph(HAPPY_PATH_STEPS))
    for var in ("_GCP_PROJECT", "_TASKS_LOCATION", "_TASKS_QUEUE", "_WORKER_BASE_URL"):
        monkeypatch.setattr(srv, var, None)
    yield srv
    # Drain any in-process _run_job_from_db tasks left by start_research before
    # the DB is truncated, so a late write can't hit an emptied table.
    leaked = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for t in leaked:
        t.cancel()
    for t in leaked:
        try:
            await t
        except BaseException:
            pass


# ---------------------------------------------------------------------------
# Tool discovery
# ---------------------------------------------------------------------------


async def test_tool_discovery(patched_server):
    tools = await patched_server.mcp.list_tools()
    tool_names = {t.name for t in tools}
    assert {"start_research", "get_research_status", "get_research_report"} <= tool_names


# ---------------------------------------------------------------------------
# start_research — creates a durable queued row
# ---------------------------------------------------------------------------


async def test_start_research_returns_job_id(patched_server):
    result = await patched_server.start_research("What is quantum computing?")
    assert "job_id" in result
    assert result["status"] == "queued"
    assert len(result["job_id"]) == 32  # uuid4().hex


async def test_start_research_non_blocking(patched_server):
    t0 = time.perf_counter()
    result = await patched_server.start_research("test question")
    assert time.perf_counter() - t0 < 1.0
    assert result["status"] == "queued"


async def test_start_research_empty_query_raises(patched_server):
    with pytest.raises(ValueError, match="must not be empty"):
        await patched_server.start_research("   ")


async def test_start_research_writes_queued_row(patched_server, monkeypatch):
    monkeypatch.setattr(patched_server, "_dispatch_job", _async_noop)
    result = await patched_server.start_research("Persisted question", max_iterations=3)
    job = _db_job(result["job_id"])
    assert job["status"] == "queued"
    assert job["max_iterations"] == 3
    assert job["agent_model"]  # provider/model captured at creation


@pytest.mark.parametrize("requested,expected", [(99, 5), (0, 1), (None, 2)])
async def test_max_iterations_clamped(patched_server, monkeypatch, requested, expected):
    monkeypatch.setattr(patched_server, "_dispatch_job", _async_noop)
    kwargs = {} if requested is None else {"max_iterations": requested}
    result = await patched_server.start_research("test", **kwargs)
    assert _db_job(result["job_id"])["max_iterations"] == expected


# ---------------------------------------------------------------------------
# Dispatch: Cloud Tasks vs in-process
# ---------------------------------------------------------------------------


async def test_dispatch_enqueues_cloud_task_when_configured(patched_server, monkeypatch):
    monkeypatch.setattr(patched_server, "_GCP_PROJECT", "proj")
    monkeypatch.setattr(patched_server, "_TASKS_LOCATION", "us-central1")
    monkeypatch.setattr(patched_server, "_TASKS_QUEUE", "auspex-jobs")
    monkeypatch.setattr(patched_server, "_WORKER_BASE_URL", "https://svc.run.app")
    enqueue = MagicMock()
    monkeypatch.setattr(patched_server, "_enqueue_cloud_task", enqueue)

    result = await patched_server.start_research("cloud task path")
    job_id = result["job_id"]
    await asyncio.sleep(0.05)  # let the to_thread enqueue run

    enqueue.assert_called_once_with(job_id)
    assert _db_job(job_id)["status"] == "queued"  # worker has not run it


async def test_dispatch_in_process_runs_job(patched_server):
    result = await patched_server.start_research("in-process path")
    status = await _await_status(patched_server, result["job_id"], "done")
    assert status["status"] == "done"


# ---------------------------------------------------------------------------
# Status transitions (read from Postgres)
# ---------------------------------------------------------------------------


async def test_status_queued_immediately(patched_server):
    result = await patched_server.start_research("test")
    status = await patched_server.get_research_status(result["job_id"])
    assert status["status"] in ("queued", "running", "done")


async def test_status_transitions_to_done(patched_server):
    result = await patched_server.start_research("What is quantum computing?")
    status = await _await_status(patched_server, result["job_id"], "done")
    assert status["status"] == "done"
    assert status["current_node"] == "writer"
    assert status["iteration"] == 1
    assert status["error"] is None


async def test_pipeline_failure_sets_error(patched_server, monkeypatch):
    monkeypatch.setattr(
        patched_server, "_graph", make_failing_graph(RuntimeError("LLM unreachable"))
    )
    job_id = "fail-1"
    patched_server._create_job(job_id, "boom", 2, "test/model")
    await patched_server._run_job_from_db(job_id)
    status = await patched_server.get_research_status(job_id)
    assert status["status"] == "error"
    assert "LLM unreachable" in status["error"]


async def test_unknown_job_id_raises(patched_server):
    with pytest.raises(ValueError, match="Unknown job_id"):
        await patched_server.get_research_status("nonexistent-job-id")


async def test_status_reads_seeded_job(patched_server):
    _seed_job("db-job-001", status="done", report="old report content")
    status = await patched_server.get_research_status("db-job-001")
    assert status["status"] == "done"
    assert status["current_node"] is None


async def test_status_error_reads_seeded_job(patched_server):
    _seed_job("db-job-002", status="error", error="LLM timeout")
    status = await patched_server.get_research_status("db-job-002")
    assert status["status"] == "error"
    assert status["error"] == "LLM timeout"


# ---------------------------------------------------------------------------
# The worker: _run_job_from_db + /internal/run-job route
# ---------------------------------------------------------------------------


async def test_run_job_from_db_drives_queued_to_done(patched_server):
    job_id = "wk-1"
    patched_server._create_job(job_id, "worker question", 2, "test/model")
    await patched_server._run_job_from_db(job_id)
    job = _db_job(job_id)
    assert job["status"] == "done"
    assert "Research Report" in job["report"]
    assert job["current_node"] == "writer"


async def test_run_job_from_db_persists_sources(patched_server):
    job_id = "wk-2"
    patched_server._create_job(job_id, "worker sources", 2, "test/model")
    await patched_server._run_job_from_db(job_id)
    report = await patched_server.get_research_report(job_id)
    assert len(report["sources"]) == 1
    assert report["sources"][0]["url"] == "http://example.com/a"


async def test_run_job_from_db_unknown_id_is_noop(patched_server):
    await patched_server._run_job_from_db("does-not-exist")  # must not raise


async def test_run_job_endpoint_processes_job(patched_server):
    job_id = "wk-3"
    patched_server._create_job(job_id, "endpoint question", 2, "test/model")
    resp = await patched_server.run_job_endpoint(_FakeRequest({"job_id": job_id}))
    assert resp.status_code == 200
    assert _db_job(job_id)["status"] == "done"


async def test_run_job_endpoint_requires_job_id(patched_server):
    resp = await patched_server.run_job_endpoint(_FakeRequest({}))
    assert resp.status_code == 400


def test_build_http_app_adds_worker_route():
    import auspex.mcp_server.server as srv

    app = srv.build_http_app(token=None)
    paths = {getattr(r, "path", None) for r in app.routes}
    assert "/internal/run-job" in paths


# ---------------------------------------------------------------------------
# Report retrieval
# ---------------------------------------------------------------------------


async def test_report_available_after_done(patched_server):
    result = await patched_server.start_research("What is quantum computing?")
    await _await_status(patched_server, result["job_id"], "done")
    report = await patched_server.get_research_report(result["job_id"])
    assert report["status"] == "done"
    assert report["report"] == "# Research Report\n\nContent here."
    assert report["sources"][0]["url"] == "http://example.com/a"


async def test_report_none_while_running(patched_server):
    _seed_job("rep-run", status="running")
    report = await patched_server.get_research_report("rep-run")
    assert report["report"] is None
    assert report["status"] == "running"


async def test_report_unknown_job_raises(patched_server):
    with pytest.raises(ValueError, match="Unknown job_id"):
        await patched_server.get_research_report("nonexistent-id")


async def test_report_reads_seeded_job_with_durable_sources(patched_server):
    _seed_job(
        "db-job-003",
        status="done",
        report="# LangGraph\n\nPersisted report.",
        sources=[{"url": "http://a.com", "summary": "S", "raw_length": 100}],
    )
    report = await patched_server.get_research_report("db-job-003")
    assert report["status"] == "done"
    assert report["report"] == "# LangGraph\n\nPersisted report."
    assert report["sources"][0]["url"] == "http://a.com"


# ---------------------------------------------------------------------------
# Resource
# ---------------------------------------------------------------------------


async def test_resource_returns_report(patched_server):
    result = await patched_server.start_research("resource test")
    await _await_status(patched_server, result["job_id"], "done")
    content = await patched_server.research_report_resource(result["job_id"])
    assert "Research Report" in content


async def test_resource_raises_for_unknown_job(patched_server):
    with pytest.raises(ValueError, match="Unknown job_id"):
        await patched_server.research_report_resource("no-such-id")


async def test_resource_raises_when_not_done(patched_server):
    _seed_job("res-run", status="running")
    with pytest.raises(ValueError):
        await patched_server.research_report_resource("res-run")


# ---------------------------------------------------------------------------
# HTTP transport + bearer auth
# ---------------------------------------------------------------------------


def test_build_http_app_disables_transport_security():
    import auspex.mcp_server.server as srv

    srv.mcp.settings.transport_security = object()
    srv.build_http_app(token=None)
    assert srv.mcp.settings.transport_security is None


def _dummy_asgi_app():
    from starlette.applications import Starlette
    from starlette.responses import PlainTextResponse
    from starlette.routing import Route

    async def ok(request):
        return PlainTextResponse("ok")

    return Starlette(routes=[Route("/mcp", ok)])


def test_bearer_auth_allows_correct_token():
    from starlette.testclient import TestClient

    from auspex.mcp_server.server import BearerAuthMiddleware

    client = TestClient(BearerAuthMiddleware(_dummy_asgi_app(), token="s3cret"))
    resp = client.get("/mcp", headers={"Authorization": "Bearer s3cret"})
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_bearer_auth_rejects_wrong_token():
    from starlette.testclient import TestClient

    from auspex.mcp_server.server import BearerAuthMiddleware

    client = TestClient(BearerAuthMiddleware(_dummy_asgi_app(), token="s3cret"))
    assert client.get("/mcp", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_bearer_auth_rejects_missing_header():
    from starlette.testclient import TestClient

    from auspex.mcp_server.server import BearerAuthMiddleware

    client = TestClient(BearerAuthMiddleware(_dummy_asgi_app(), token="s3cret"))
    assert client.get("/mcp").status_code == 401
