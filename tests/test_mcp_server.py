"""Unit tests for the Auspex MCP server.

The pipeline (``_graph``) is mocked so no LLM calls or network access occur.
The job store is Postgres (see docs/adr/0004): these tests require a reachable
database (``DATABASE_URL``, default the local docker-compose Postgres) and are
skipped if none is available. CI provides a Postgres service.
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
    """True if Postgres is reachable AND the jobs/sources schema exists.

    The schema is created by `alembic upgrade head` as a separate step (CI runs
    it; locally it is run once) — tests do not migrate in-process.
    """
    try:
        conn = _connect()
    except Exception:
        return False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.jobs'), to_regclass('public.sources')")
            jobs, sources = cur.fetchone()
        return jobs is not None and sources is not None
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


@pytest_asyncio.fixture
async def patched_server(monkeypatch):
    """MCP server module with _graph mocked and the test DB wired in.

    Async so teardown can drain fire-and-forget _run_job tasks: tests that call
    start_research without awaiting completion leave a pending task that would
    otherwise wedge the event loop's teardown.
    """
    import auspex.mcp_server.server as srv

    monkeypatch.setattr(srv, "_DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setattr(srv, "_graph", make_mock_graph(HAPPY_PATH_STEPS))
    srv._mcp_jobs.clear()
    yield srv
    leaked = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    for t in leaked:
        t.cancel()
    for t in leaked:
        try:
            await t
        except BaseException:
            pass
    srv._mcp_jobs.clear()


# ---------------------------------------------------------------------------
# Tool discovery
# ---------------------------------------------------------------------------


async def test_tool_discovery(patched_server):
    """All three tools must be registered with the FastMCP instance."""
    import auspex.mcp_server.server as srv

    tools = await srv.mcp.list_tools()
    tool_names = {t.name for t in tools}
    assert "start_research" in tool_names
    assert "get_research_status" in tool_names
    assert "get_research_report" in tool_names


# ---------------------------------------------------------------------------
# start_research
# ---------------------------------------------------------------------------


async def test_start_research_returns_job_id(patched_server):
    result = await patched_server.start_research("What is quantum computing?")
    assert "job_id" in result
    assert result["status"] == "queued"
    assert len(result["job_id"]) == 32  # uuid4().hex


async def test_start_research_non_blocking(patched_server):
    """start_research must return in <1s regardless of pipeline duration."""
    t0 = time.perf_counter()
    result = await patched_server.start_research("test question")
    elapsed = time.perf_counter() - t0
    assert elapsed < 1.0
    assert result["status"] == "queued"


async def test_start_research_empty_query_raises(patched_server):
    with pytest.raises(ValueError, match="must not be empty"):
        await patched_server.start_research("   ")


async def test_start_research_max_iterations_capped(patched_server):
    result = await patched_server.start_research("test", max_iterations=99)
    job_id = result["job_id"]
    assert patched_server._mcp_jobs[job_id]["max_iterations"] == 5


async def test_start_research_max_iterations_minimum(patched_server):
    result = await patched_server.start_research("test", max_iterations=0)
    job_id = result["job_id"]
    assert patched_server._mcp_jobs[job_id]["max_iterations"] == 1


async def test_start_research_max_iterations_default(patched_server):
    result = await patched_server.start_research("test")
    job_id = result["job_id"]
    assert patched_server._mcp_jobs[job_id]["max_iterations"] == 2


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------


async def test_status_queued_immediately(patched_server):
    result = await patched_server.start_research("test")
    job_id = result["job_id"]
    status = await patched_server.get_research_status(job_id)
    assert status["status"] in ("queued", "running")


async def test_status_transitions_to_done(patched_server):
    result = await patched_server.start_research("What is quantum computing?")
    job_id = result["job_id"]
    await asyncio.sleep(0.1)

    status = await patched_server.get_research_status(job_id)
    assert status["status"] == "done"
    assert status["current_node"] == "writer"
    assert status["iteration"] == 1
    assert status["error"] is None


async def test_status_error_on_pipeline_failure(monkeypatch):
    import auspex.mcp_server.server as srv

    monkeypatch.setattr(srv, "_DATABASE_URL", TEST_DATABASE_URL)
    monkeypatch.setattr(srv, "_graph", make_failing_graph(RuntimeError("LLM unreachable")))
    srv._mcp_jobs.clear()

    result = await srv.start_research("test")
    job_id = result["job_id"]
    await asyncio.sleep(0.1)

    status = await srv.get_research_status(job_id)
    assert status["status"] == "error"
    assert "LLM unreachable" in status["error"]

    srv._mcp_jobs.clear()


async def test_unknown_job_id_raises(patched_server):
    with pytest.raises(ValueError, match="Unknown job_id"):
        await patched_server.get_research_status("nonexistent-job-id")


# ---------------------------------------------------------------------------
# Report retrieval
# ---------------------------------------------------------------------------


async def test_report_available_after_done(patched_server):
    result = await patched_server.start_research("What is quantum computing?")
    job_id = result["job_id"]
    await asyncio.sleep(0.1)

    report = await patched_server.get_research_report(job_id)
    assert report["status"] == "done"
    assert report["report"] == "# Research Report\n\nContent here."
    assert len(report["sources"]) == 1
    assert report["sources"][0]["url"] == "http://example.com/a"


async def test_report_none_while_running(patched_server):
    result = await patched_server.start_research("test")
    job_id = result["job_id"]
    report = await patched_server.get_research_report(job_id)
    assert report["report"] is None


async def test_report_unknown_job_raises(patched_server):
    with pytest.raises(ValueError, match="Unknown job_id"):
        await patched_server.get_research_report("nonexistent-id")


# ---------------------------------------------------------------------------
# Persistence + Postgres fallback
# ---------------------------------------------------------------------------


async def test_job_persisted_to_postgres_on_completion(patched_server):
    result = await patched_server.start_research("Persisted question")
    job_id = result["job_id"]
    await asyncio.sleep(0.1)

    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT status, report, agent_model FROM jobs WHERE id = %s", (job_id,))
            row = cur.fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row[0] == "done"
    assert "Research Report" in row[1]
    assert row[2]  # agent_model captured (provider/model)


async def test_sources_persisted_to_postgres_on_completion(patched_server):
    result = await patched_server.start_research("with sources")
    job_id = result["job_id"]
    await asyncio.sleep(0.1)

    conn = _connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT url, summary, raw_length FROM sources WHERE job_id = %s", (job_id,)
            )
            rows = cur.fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0][0] == "http://example.com/a"
    assert rows[0][2] == 800


async def test_status_falls_back_to_postgres(patched_server):
    _seed_job("db-job-001", status="done", report="old report content")
    status = await patched_server.get_research_status("db-job-001")
    assert status["status"] == "done"
    assert status["current_node"] is None
    assert status["iteration"] is None


async def test_status_error_falls_back_to_postgres(patched_server):
    _seed_job("db-job-002", status="error", error="LLM timeout")
    status = await patched_server.get_research_status("db-job-002")
    assert status["status"] == "error"
    assert status["error"] == "LLM timeout"


async def test_report_falls_back_to_postgres_with_durable_sources(patched_server):
    _seed_job(
        "db-job-003",
        status="done",
        report="# LangGraph\n\nPersisted report.",
        sources=[{"url": "http://a.com", "summary": "S", "raw_length": 100}],
    )
    report = await patched_server.get_research_report("db-job-003")
    assert report["status"] == "done"
    assert report["report"] == "# LangGraph\n\nPersisted report."
    assert len(report["sources"]) == 1  # sources now durable, not lost
    assert report["sources"][0]["url"] == "http://a.com"


# ---------------------------------------------------------------------------
# In-memory job eviction (memory-leak fix)
# ---------------------------------------------------------------------------


async def test_report_evicts_completed_job(patched_server):
    result = await patched_server.start_research("evict me")
    job_id = result["job_id"]
    await asyncio.sleep(0.1)
    assert job_id in patched_server._mcp_jobs

    report = await patched_server.get_research_report(job_id)
    assert report["status"] == "done"
    assert report["sources"]
    assert job_id not in patched_server._mcp_jobs


async def test_status_after_eviction_falls_back_to_postgres(patched_server):
    result = await patched_server.start_research("evict then status")
    job_id = result["job_id"]
    await asyncio.sleep(0.1)
    await patched_server.get_research_report(job_id)  # triggers eviction
    assert job_id not in patched_server._mcp_jobs

    status = await patched_server.get_research_status(job_id)
    assert status["status"] == "done"


async def test_running_job_not_evicted(patched_server):
    result = await patched_server.start_research("still running")
    job_id = result["job_id"]
    patched_server._mcp_jobs[job_id]["status"] = "running"

    report = await patched_server.get_research_report(job_id)
    assert report["report"] is None
    assert job_id in patched_server._mcp_jobs


# ---------------------------------------------------------------------------
# Resource
# ---------------------------------------------------------------------------


async def test_resource_returns_report(patched_server):
    result = await patched_server.start_research("resource test")
    job_id = result["job_id"]
    await asyncio.sleep(0.1)

    content = await patched_server.research_report_resource(job_id)
    assert "Research Report" in content


async def test_resource_raises_for_unknown_job(patched_server):
    with pytest.raises(ValueError, match="Unknown job_id"):
        await patched_server.research_report_resource("no-such-id")


async def test_resource_raises_when_not_done(patched_server):
    result = await patched_server.start_research("pending resource")
    job_id = result["job_id"]
    patched_server._mcp_jobs[job_id]["status"] = "running"

    with pytest.raises(ValueError):
        await patched_server.research_report_resource(job_id)


# ---------------------------------------------------------------------------
# HTTP transport + bearer auth
# ---------------------------------------------------------------------------


def test_build_http_app_disables_transport_security():
    """Regression: --http must clear the localhost-only DNS-rebinding guard."""
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

    app = BearerAuthMiddleware(_dummy_asgi_app(), token="s3cret")
    client = TestClient(app)
    resp = client.get("/mcp", headers={"Authorization": "Bearer s3cret"})
    assert resp.status_code == 200
    assert resp.text == "ok"


def test_bearer_auth_rejects_wrong_token():
    from starlette.testclient import TestClient

    from auspex.mcp_server.server import BearerAuthMiddleware

    app = BearerAuthMiddleware(_dummy_asgi_app(), token="s3cret")
    client = TestClient(app)
    resp = client.get("/mcp", headers={"Authorization": "Bearer nope"})
    assert resp.status_code == 401


def test_bearer_auth_rejects_missing_header():
    from starlette.testclient import TestClient

    from auspex.mcp_server.server import BearerAuthMiddleware

    app = BearerAuthMiddleware(_dummy_asgi_app(), token="s3cret")
    client = TestClient(app)
    resp = client.get("/mcp")
    assert resp.status_code == 401
