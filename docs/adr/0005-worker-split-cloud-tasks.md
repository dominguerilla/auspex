# 0005 — Durable job queue (worker split) via Cloud Tasks

| | |
|---|---|
| **Status** | Accepted |
| **Date** | 2026-06-17 |
| **Owner** | Carlos |
| **Related** | [0004](0004-host-mcp-server-on-aws-postgres.md) (resolves its deferred worker split), [proposals/0002](../proposals/0002-hosting-auspex.md), `auspex/mcp_server/server.py`, [infra/ARCHITECTURE.md](../../infra/ARCHITECTURE.md) |

## Context

[ADR 0004](0004-host-mcp-server-on-aws-postgres.md) shipped a "polished core,"
single-instance MCP server and **deferred the web↔worker split to v1.1**, on the
premise that v1 left a clean seam. On the live GCP Cloud Run deployment that
deferred design has now broken in practice — the in-process job model collides
with Cloud Run's request-driven lifecycle.

Concretely, in `server.py` today:

- `start_research` stores the job **only in one instance's RAM** (`_mcp_jobs`) and
  runs it as a post-response background task (`asyncio.create_task(_run_job)`).
- `_run_job` writes to **Postgres only on completion** (`done`/`error`). A
  `queued`/`running` job exists nowhere but that instance's memory.
- `get_research_status` reads memory, then falls back to Postgres, then raises
  `Unknown job_id`.

With `min_instances = 0` (scale to zero), Cloud Run reclaims the idle instance
after `start_research` returns its HTTP response — killing the background task
*and* wiping `_mcp_jobs` before the job ever reaches Postgres. The later
`get_research_status` call cold-starts a fresh instance (or routes to a second
one) with empty memory and no Postgres row → **`Unknown job_id`**. This was
observed end-to-end via a remote agent (Hermes) on 2026-06-17. It is not an auth
failure: `start_research` succeeds, and the error is an app-level `ValueError`,
not a `401`.

The only single-instance stopgap (`min_instances = 1`, `max_instances = 1`,
`cpu_idle = false`) makes it work but pins an always-on, always-allocated-CPU
instance (~$45/mo) — which negates the scale-to-zero cost advantage that motived
the move to Cloud Run ([0004](0004-host-mcp-server-on-aws-postgres.md) revision).
It is acceptable only as a temporary test, not the steady state.

## Decision

Split job **execution** from request handling using a durable queue, so job state
lives in Postgres from creation and the work runs inside a request Cloud Run keeps
alive. One image/service, two roles.

1. **Persist from the start.** `start_research` writes a `queued` job row to
   Postgres and returns the `job_id` immediately. In-memory `_mcp_jobs` is no
   longer authoritative.
2. **Durable trigger.** `start_research` enqueues a **Cloud Tasks** task targeting
   an internal worker route, instead of `asyncio.create_task`.
3. **Synchronous worker route.** A new `/internal/run-job` endpoint (added to the
   existing `build_http_app`) loads the job and runs the graph **within the HTTP
   request**, updating Postgres `queued → running → done/error` and writing
   sources. Because the work runs inside an *active* request, Cloud Run keeps the
   instance and CPU for the job's full duration — so **`cpu_idle = false` is no
   longer needed**.
4. **State reads from Postgres.** `get_research_status` / `get_research_report`
   become Postgres reads, authoritative regardless of which instance serves them.
5. **Reuse existing auth.** Cloud Tasks attaches the existing `AUSPEX_MCP_TOKEN`
   bearer header on its POST; `BearerAuthMiddleware` already protects the route.
   No new auth code.
6. **Return to scale-to-zero.** `min_instances = 0`, `cpu_idle = true`; raise the
   Cloud Run request `timeout` (default 300s → ~1800s) so a multi-minute job
   isn't cut off. The timeout is a maximum, so quick tool calls are unaffected.

**Infra (Terraform):** a `google_cloud_tasks_queue`, enable `cloudtasks.googleapis.com`,
grant the runtime service account `roles/cloudtasks.enqueuer`, wire queue +
worker-URL env vars, and the timeout / `cpu_idle` / `min_instances` changes above.

**Schema:** none required for the minimal version — the `jobs.status` column
already exists; we simply write `queued`/`running` to it earlier. *Optional:* add
`current_node` / `iteration` columns (one Alembic migration) to surface live
progress, which currently lives only in memory.

### Rejected alternatives

- **Always-on instance** (`min=1`, `cpu_idle=false`): works, but ~$45/mo defeats
  the cost model. Kept only as a throwaway test of the pipeline.
- **Cloud Run Jobs** (run-to-completion containers): heavier to trigger per
  request and to pass the `job_id`; better suited to batch/scheduled work.
- **Pub/Sub push**: more moving parts than Cloud Tasks for single-job triggering
  with retries.

## Consequences

- Jobs survive instance churn and scale-to-zero; status/report work from any
  instance; idle cost returns to **~$0**. This resolves 0004's noted "if the
  instance is reclaimed mid-job, the job is lost" caveat (Cloud Tasks retries; the
  job row records progress).
- **Closes the deferred worker split** from [0004](0004-host-mcp-server-on-aws-postgres.md).
  As predicted, the polished-core foundation (Postgres-backed state, stateless
  server) made this an additive change, not a rewrite.
- One service with two roles keeps the deploy simple; promoting `/internal/run-job`
  to a separate worker Cloud Run service later is itself additive.
- Adds a managed dependency (Cloud Tasks); its free tier covers the daily-report
  volume.
- **New failure mode:** a job stuck in `running` if the worker dies without writing
  a terminal state. Mitigated by Cloud Tasks retries and the request `timeout`; a
  stale-job reaper / heartbeat is a follow-up, not a v1.1 blocker.
- Tests: add coverage that `start_research` writes a `queued` row and enqueues a
  task, and that `/internal/run-job` drives Postgres through the states (graph
  mocked). The existing CI Postgres job covers it; no native-Windows change.
- Docs: `architecture.md` and `mcp.md` gain the queue + worker-route description;
  [infra/ARCHITECTURE.md](../../infra/ARCHITECTURE.md) gains the Cloud Tasks hop.
