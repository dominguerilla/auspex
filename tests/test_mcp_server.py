"""Unit tests for the Auspex MCP server.

All tests mock _graph so no LLM calls or network access occur.
"""

import asyncio
import sqlite3
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Helpers
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


FAILING_STEPS: list[dict] = []  # empty — astream raises instead


def make_failing_graph(exc: Exception):
    async def fake_astream(initial_state):
        raise exc
        yield  # make it a generator

    mock = MagicMock()
    mock.astream = fake_astream
    return mock


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_server(monkeypatch, tmp_path):
    """Import the MCP server module with _DB_PATH and _graph both patched."""
    import auspex.mcp_server.server as srv

    monkeypatch.setattr(srv, "_DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(srv, "_graph", make_mock_graph(HAPPY_PATH_STEPS))
    srv._mcp_jobs.clear()
    srv._init_db()
    yield srv
    srv._mcp_jobs.clear()


@pytest.fixture
def seeded_db(tmp_path) -> Path:
    """Return a pre-populated jobs.db path with one completed job."""
    db_path = tmp_path / "jobs.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            question TEXT NOT NULL,
            status TEXT NOT NULL,
            report TEXT,
            error TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at TEXT,
            max_iterations INTEGER,
            duration_ms INTEGER
        )
        """
    )
    conn.execute(
        "INSERT INTO jobs (id, question, status, report) VALUES (?, ?, 'done', ?)",
        ("db-job-001", "What is LangGraph?", "# LangGraph\n\nPersisted report."),
    )
    conn.execute(
        "INSERT INTO jobs (id, question, status, error) VALUES (?, ?, 'error', ?)",
        ("db-job-002", "Bad question", "LLM timeout"),
    )
    conn.commit()
    conn.close()
    return db_path


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
    """Status should be 'queued' right after start_research returns."""
    result = await patched_server.start_research("test")
    job_id = result["job_id"]
    status = await patched_server.get_research_status(job_id)
    # Immediately after create_task — could be queued or running
    assert status["status"] in ("queued", "running")


async def test_status_transitions_to_done(patched_server):
    result = await patched_server.start_research("What is quantum computing?")
    job_id = result["job_id"]
    # Let the event loop run _run_job to completion
    await asyncio.sleep(0.1)

    status = await patched_server.get_research_status(job_id)
    assert status["status"] == "done"
    assert status["current_node"] == "writer"
    assert status["iteration"] == 1
    assert status["error"] is None


async def test_status_error_on_pipeline_failure(monkeypatch, tmp_path):
    import auspex.mcp_server.server as srv

    monkeypatch.setattr(srv, "_DB_PATH", tmp_path / "jobs.db")
    monkeypatch.setattr(srv, "_graph", make_failing_graph(RuntimeError("LLM unreachable")))
    srv._mcp_jobs.clear()
    srv._init_db()

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
    """Report should be None when job is still in progress."""
    result = await patched_server.start_research("test")
    job_id = result["job_id"]
    # Don't yield to the event loop — job should still be queued/starting
    report = await patched_server.get_research_report(job_id)
    assert report["report"] is None


async def test_report_unknown_job_raises(patched_server):
    with pytest.raises(ValueError, match="Unknown job_id"):
        await patched_server.get_research_report("nonexistent-id")


# ---------------------------------------------------------------------------
# SQLite fallback
# ---------------------------------------------------------------------------


async def test_status_falls_back_to_sqlite(monkeypatch, seeded_db):
    import auspex.mcp_server.server as srv

    monkeypatch.setattr(srv, "_DB_PATH", seeded_db)
    srv._mcp_jobs.clear()

    status = await srv.get_research_status("db-job-001")
    assert status["status"] == "done"
    assert status["current_node"] is None
    assert status["iteration"] is None

    srv._mcp_jobs.clear()


async def test_status_error_falls_back_to_sqlite(monkeypatch, seeded_db):
    import auspex.mcp_server.server as srv

    monkeypatch.setattr(srv, "_DB_PATH", seeded_db)
    srv._mcp_jobs.clear()

    status = await srv.get_research_status("db-job-002")
    assert status["status"] == "error"
    assert status["error"] == "LLM timeout"

    srv._mcp_jobs.clear()


async def test_report_falls_back_to_sqlite(monkeypatch, seeded_db):
    import auspex.mcp_server.server as srv

    monkeypatch.setattr(srv, "_DB_PATH", seeded_db)
    srv._mcp_jobs.clear()

    report = await srv.get_research_report("db-job-001")
    assert report["status"] == "done"
    assert report["report"] == "# LangGraph\n\nPersisted report."
    assert report["sources"] == []  # never persisted

    srv._mcp_jobs.clear()


async def test_job_persisted_to_sqlite_on_completion(patched_server, tmp_path):
    result = await patched_server.start_research("Persisted question")
    job_id = result["job_id"]
    await asyncio.sleep(0.1)

    # Verify the job was written to the patched DB
    conn = sqlite3.connect(patched_server._DB_PATH)
    row = conn.execute("SELECT status, report FROM jobs WHERE id = ?", (job_id,)).fetchone()
    conn.close()
    assert row is not None
    assert row[0] == "done"
    assert "Research Report" in row[1]


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
    # Manually set status to running without letting it complete
    patched_server._mcp_jobs[job_id]["status"] = "running"

    with pytest.raises(ValueError):
        await patched_server.research_report_resource(job_id)
