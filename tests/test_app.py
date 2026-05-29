"""Tests for app.py — /config endpoint, schema migration, and snapshot serialization.

Each test that touches the FastAPI app gets a freshly reloaded module inside a
tmp_path cwd, so the on-disk `jobs.db` is isolated per test.
"""

import importlib
import sqlite3
import time

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_module(tmp_path, monkeypatch):
    """Reload app inside a tmp cwd so each test gets a fresh jobs.db."""
    monkeypatch.chdir(tmp_path)
    import app as _app
    importlib.reload(_app)
    return _app


@pytest.fixture
def client(app_module):
    return TestClient(app_module.app)


# ── /config ──────────────────────────────────────────────────────────────

def test_config_returns_expected_shape(client):
    r = client.get("/config")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {
        "provider", "model", "provider_label",
        "max_iterations_default", "max_iterations_ceiling", "node_order",
    }


def test_config_node_order_matches_app_constant(client, app_module):
    body = client.get("/config").json()
    assert body["node_order"] == app_module.NODE_ORDER


def test_config_max_iterations_match_app_constants(client, app_module):
    body = client.get("/config").json()
    assert body["max_iterations_default"] == app_module.MAX_ITERATIONS_DEFAULT
    assert body["max_iterations_ceiling"] == app_module.MAX_ITERATIONS_CEILING


def test_config_reflects_llm_env_override(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "huggingface")
    monkeypatch.setenv("HF_MODEL", "test/custom-model")
    import app as _app
    importlib.reload(_app)
    with TestClient(_app.app) as c:
        body = c.get("/config").json()
    assert body["provider"] == "huggingface"
    assert body["model"] == "test/custom-model"
    assert body["provider_label"] == "HF Inference"


# ── schema migration ─────────────────────────────────────────────────────

def test_init_db_creates_all_columns_on_fresh_db(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    import app as _app
    importlib.reload(_app)
    cols = {row[1] for row in _app.db.execute("PRAGMA table_info(jobs)")}
    assert {"max_iterations", "duration_ms", "completed_at"} <= cols


def test_init_db_adds_missing_columns_to_legacy_db(tmp_path, monkeypatch):
    """Simulate an older jobs.db that predates max_iterations/duration_ms."""
    monkeypatch.chdir(tmp_path)
    legacy_conn = sqlite3.connect(tmp_path / "jobs.db")
    legacy_conn.execute(
        """
        CREATE TABLE jobs (
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
    legacy_conn.execute(
        "INSERT INTO jobs (id, question, status, report) VALUES (?, ?, 'done', ?)",
        ("legacy", "old question", "old report"),
    )
    legacy_conn.commit()
    legacy_conn.close()

    import app as _app
    importlib.reload(_app)

    cols = {row[1] for row in _app.db.execute("PRAGMA table_info(jobs)")}
    assert "max_iterations" in cols
    assert "duration_ms" in cols

    # Legacy row still readable; new columns are NULL.
    row = _app.db.execute(
        "SELECT question, max_iterations, duration_ms FROM jobs WHERE id = ?",
        ("legacy",),
    ).fetchone()
    assert row == ("old question", None, None)


def test_init_db_is_idempotent(tmp_path, monkeypatch):
    """Calling init_db a second time on a current-schema DB must not error."""
    monkeypatch.chdir(tmp_path)
    import app as _app
    importlib.reload(_app)
    # First reload already called init_db; call it again on the same file.
    _app.db.close()
    conn = _app.init_db()
    cols = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
    assert "max_iterations" in cols
    conn.close()


# ── snapshot serialization ───────────────────────────────────────────────

def test_snapshot_404_for_unknown_id(client):
    r = client.get("/research/does-not-exist")
    assert r.status_code == 404
    assert r.json() == {"error": "expired"}


def test_snapshot_running_job_includes_new_fields(client, app_module):
    """Running jobs in the in-memory dict should expose max_iterations,
    duration_ms (None while running), and started_at_ms."""
    job = app_module.Job("what is X?", max_iterations=4)
    app_module.jobs["job-running"] = job

    body = client.get("/research/job-running").json()
    assert body["status"] == "running"
    assert body["question"] == "what is X?"
    assert body["max_iterations"] == 4
    assert body["duration_ms"] is None
    # started_at_ms should be a recent epoch in ms.
    now_ms = time.time() * 1000
    assert abs(body["started_at_ms"] - now_ms) < 5000


def test_snapshot_completed_job_from_db_returns_new_fields(client, app_module):
    """Completed jobs read from sqlite should include max_iterations/duration_ms."""
    app_module.db.execute(
        "INSERT INTO jobs "
        "(id, question, status, report, max_iterations, duration_ms, completed_at) "
        "VALUES (?, ?, 'done', ?, ?, ?, datetime('now'))",
        ("done-1", "what?", "the report", 3, 42000),
    )
    app_module.db.commit()

    body = client.get("/research/done-1").json()
    assert body == {
        "status": "done",
        "question": "what?",
        "max_iterations": 3,
        "duration_ms": 42000,
        "events": [],
        "report": "the report",
        "error": None,
    }


def test_snapshot_legacy_db_row_returns_null_for_new_fields(client, app_module):
    """A row inserted before the migration should still snapshot cleanly."""
    app_module.db.execute(
        "INSERT INTO jobs (id, question, status, report, completed_at) "
        "VALUES (?, ?, 'done', ?, datetime('now'))",
        ("legacy", "legacy q", "legacy report"),
    )
    app_module.db.commit()

    body = client.get("/research/legacy").json()
    assert body["status"] == "done"
    assert body["max_iterations"] is None
    assert body["duration_ms"] is None


# ── Job book-keeping ─────────────────────────────────────────────────────

def test_job_init_carries_max_iterations(app_module):
    job = app_module.Job("q", max_iterations=5)
    assert job.max_iterations == 5
    assert job.duration_ms is None
    assert job.status == "running"


def test_job_append_tags_elapsed_s(app_module):
    job = app_module.Job("q", max_iterations=1)
    job.append("node_complete", {"node": "orchestrator"})
    assert len(job.events) == 1
    evt = job.events[0]
    assert evt["event"] == "node_complete"
    assert evt["data"]["node"] == "orchestrator"
    assert "elapsed_s" in evt["data"]
    assert evt["data"]["elapsed_s"] >= 0


# ── /research request validation ─────────────────────────────────────────

def test_research_rejects_max_iterations_above_ceiling(client, app_module):
    r = client.post(
        "/research",
        json={"question": "ok", "max_iterations": app_module.MAX_ITERATIONS_CEILING + 1},
    )
    assert r.status_code == 422


def test_research_rejects_blank_question(client):
    r = client.post("/research", json={"question": "", "max_iterations": 2})
    assert r.status_code == 422
