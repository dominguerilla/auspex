# 0003 — Use SQLite for completed-job persistence in the web server

| | |
|---|---|
| **Status** | Accepted *(inferred — confirm)* |
| **Date** | 2026-05-28 (inferred from "Use FASTAPI + stepper frontend, job queuing, shareable report URLs") |
| **Evidence** | `app.py:54-78`, `app.py:195-213`, `README.md:138-139` |

## Context

The FastAPI server holds live job state in an in-memory `jobs: dict[str, Job]`. Once a job finishes, the in-memory object is the only copy. If the client navigates away and returns — or shares the `/r/{job_id}` URL with someone else — the in-memory dict may have been garbage-collected.

Options considered:
- **In-memory only** — simple, but reports are lost on tab close or server restart.
- **SQLite** — zero-config, zero-dependency, single file; enough for one-container deployments.
- **Postgres / Redis** — persistent across restarts, horizontally scalable, but requires an external service not available on HF Spaces free tier.

## Decision

Write completed jobs (id, question, status, report, error, created_at, completed_at, max_iterations, duration_ms) to `jobs.db` (SQLite) via `sqlite3` from the standard library. The in-memory `Job` object handles the live run; after completion the row is inserted into SQLite. On `GET /research/{job_id}`, the server checks in-memory first, then falls back to SQLite.

## Consequences

- Shareable URLs (`/r/{job_id}`) work across tab closes and page refreshes within a single container lifetime.
- On HF Spaces free tier the container filesystem is ephemeral — `jobs.db` is wiped on every redeploy. This is accepted and documented in the UI.
- The schema is migrated forward with `ALTER TABLE ... ADD COLUMN` guards (`app.py:72-77`) so old DB files from earlier deployments don't break.
- A second container instance would have its own `jobs.db` — this design is single-instance only.
