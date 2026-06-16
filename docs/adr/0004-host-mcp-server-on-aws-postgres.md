# 0004 — Host the MCP server on AWS with Postgres-backed state

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-06-16 |
| **Owner** | Carlos |
| **Related** | [0003](0003-sqlite-job-persistence.md) (scoped, not superseded), [proposals/0002](../proposals/0002-hosting-auspex.md), `auspex/mcp_server/server.py` |

## Context

The MCP server (`auspex/mcp_server/`) is to be hosted online so remote agents can
call it — first use case: a cron'd agent runs a daily research report. A secondary,
explicit goal is a polished portfolio/resume artifact demonstrating production
engineering. The design discussion is captured in [proposals/0002](../proposals/0002-hosting-auspex.md);
this ADR records the decisions that came out of it.

[ADR 0003](0003-sqlite-job-persistence.md) chose SQLite for the **web server**
(`app.py`) on HF Spaces and notes it is "single-instance only." Hosting the MCP
server as a real service requires durable, concurrent state that survives instance
replacement — which SQLite-on-local-disk cannot provide.

## Decision

For the **MCP server** (not `app.py`):

1. **Host on AWS.** App Runner or Fargate for compute, **RDS PostgreSQL** for state,
   Secrets Manager for credentials, ACM/ALB (or App Runner built-in) for TLS,
   EventBridge Scheduler for the external daily trigger.
2. **Postgres-backed state** via `psycopg`, replacing the SQLite job store. Schema is
   versioned with **Alembic using raw-SQL migrations** (no ORM in the app). Adds a
   durable `sources` table and an `agent_model` column (see 0002).
3. **Stateless server** (`stateless_http=True`) and **per-agent API keys** — the
   foundation that makes horizontal scale a later config change, not a rewrite.
4. **v1 scope = "polished core," single-instance.** The web↔worker split and
   scale-to-zero are **deferred to v1.1**; v1 leaves a clean seam (execution depends
   only on Postgres-flowed state) and documents the scale-out path.
5. **LLM via cloud API** (OpenAI / Anthropic / Nous through the existing `get_llm()`
   factory) — near-zero idle cost, scale-to-zero-friendly later. Self-hosted Ollama
   (always-on GPU) is rejected for the hosted deployment.

## Consequences

- **0003 is scoped, not superseded.** `app.py` + the React `/r/{job_id}` web UI keep
  SQLite on HF Spaces; the MCP server diverges to Postgres on AWS. The two
  deployments no longer share a `jobs.db` — acceptable because the hosted MCP server
  does not run the web UI. If they are ever co-deployed, revisit.
- **The "tests fully mocked, no server needed" invariant changes** for MCP DB tests:
  they now require Postgres (CI gets a Postgres service; local dev uses
  `docker-compose`). Pure-unit tests (graph, agents) stay Postgres-free.
- `_init_db()`'s hand-rolled `CREATE TABLE`/`ALTER TABLE` is retired in favor of
  Alembic `upgrade head`.
- Worker split, vector DB, and the 0003-evals feature remain roadmap items; v1's
  Postgres + stateless foundation makes each an additive change.
- A small always-on compute floor (no scale-to-zero at v1) is accepted; idle LLM
  cost is ~$0 because the provider is a pay-per-token API.
