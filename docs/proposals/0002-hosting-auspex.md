# 0002 — Hosting Auspex: Online MCP Server, Daily-Report to Customer-Grade

| | |
|---|---|
| **Status** | Proposed |
| **Created** | 2026-06-15 |
| **Owner** | Carlos |
| **Related** | `auspex/mcp_server/server.py`, `auspex/mcp_server/__main__.py`, `app.py`, `Dockerfile`, `.github/workflows/deploy-hf-spaces.yml` |

> A design sketch, not a commitment. The goal is that a future reader can decide
> whether this is worth building and start without re-deriving the discussion.

---

## Problem

The MCP server (`auspex/mcp_server/`) now runs over stdio and streamable HTTP with
bearer-token auth, which is enough for a Hermes agent on the LAN. The next step is
to **host it online** so a remote Hermes agent can call it — concretely, to run a
**daily research report** on a topic — and to do so in a way that could *grow* to
serve a swarm of agents without a rewrite.

Two design facts in the current code stand in the way of that growth:

1. **Execution is in-process.** `start_research` runs the pipeline via
   `asyncio.create_task(_run_job(...))` *inside* the web-server process. Research
   takes minutes (LLM calls + synchronous web scraping via `requests`), so a single
   box's event loop + thread pool is the throughput ceiling.
2. **State is in-process.** `_mcp_jobs` is an in-memory dict and `jobs.db` is
   SQLite on local disk. Both are local to one instance — so you can't put two
   instances behind a load balancer (a `start_research` on instance A and the
   follow-up `get_research_status` on instance B see different worlds).

Neither bites at daily-report scale (one caller, one job a day). Both become walls
the moment you want redundancy or concurrency. The aim is to fix the *state*
problem now (cheap, unlocks everything) and defer the *execution* problem until
load actually demands it.

## Goals

- Auspex's MCP server reachable online over HTTPS, authenticated, hosting a daily
  Hermes report end-to-end.
- An architecture where scaling to many concurrent agents is a **dial to turn**
  (add workers), not a re-architecture.
- Operable like a service someone depends on: observable, restorable, alertable.
  (The operational track itself lives in [reference/operations.md](../reference/operations.md).)

## Non-goals (for the first cut)

- The swarm itself — queue + worker fleet is designed-for, not built now.
- Multi-tenancy / per-customer isolation beyond per-agent API keys.
- RAG / vector knowledge sources and reuse of Auspex's own DB as a corpus —
  explicitly deferred (see [0001](0001-source-router.md) for source expansion).
- Job cancellation, autoscaling policy, A2A.

---

## Sketch

### Current shape vs. target shape

```
NOW  (single process, single box)
  Hermes ──HTTP──► MCP server ──create_task──► pipeline ──► _mcp_jobs (mem)
                                                          └─► jobs.db (local SQLite)

TARGET (stateless front door + externalized state; workers added when needed)
  Hermes ──HTTPS──► [ingress/TLS] ──► MCP server (stateless, N replicas)
                                          │ enqueue
                                          ▼
                                    [job queue] ──► worker(s) ──► pipeline
                                          │                          │
                                          └──────────► Postgres ◄────┘
                                                   (jobs + state)
```

The MCP server stops *running* jobs and instead **enqueues** them and **reads
state from Postgres**. Whether there is 1 worker (daily-report rung) or 20 (swarm
rung), the server code is identical.

### The one change that unlocks scale: externalize state

Replace the SQLite + in-memory pair with **managed Postgres** holding all job
state. The current `jobs` table maps over almost unchanged; the work is:

- Swap `sqlite3` calls in `server.py` (`_get_db`, `_persist_job`,
  `_read_job_from_db`) for a Postgres client.
- Drop `_mcp_jobs` as a source of truth — it becomes, at most, a local read cache.
  `get_research_status` / `get_research_report` read Postgres so any replica can
  answer for any job.
- Keep `sources` (currently in-memory only) in a Postgres column or side table if
  you want them durable; otherwise document that they remain best-effort.

Once state is external and the server holds nothing job-specific in memory, the
server is **stateless** and horizontally scalable — the precondition for every
later step.

> **Storage clarification.** Postgres is the answer to *durable, concurrent job
> state*. A **vector DB is a different tool for a different problem** (semantic
> similarity), and is not part of this proposal. When query-dedup or a research
> knowledge base is wanted later, `pgvector` can ride on the same Postgres — no new
> system. Don't adopt vectors as a "more robust store"; adopt Postgres for that.

### Execution: in-process now, queue later

At the daily-report rung, keep `create_task` but run **one worker process** (the
same container image, a `--worker` entrypoint) that owns execution, while the
**server** only enqueues and reads. Even with an in-memory queue this enforces the
separation that matters.

At the swarm rung, swap the in-memory queue for a real one (Arq/Celery/RQ, or
cloud-native SQS / Azure Service Bus) and run a **worker pool**. Because the server
is already stateless and state already lives in Postgres, this is additive.

### Auth model

Graduate the single static `AUSPEX_MCP_TOKEN` to **per-agent API keys**:

| Model | Gives you | Verdict |
|---|---|---|
| Single static token (today) | Trivial; no identity, no revocation | LAN only |
| **Per-agent API keys** | Revocation, per-agent quotas, usage attribution | **Recommended** |
| OAuth2 / OIDC | Standard delegated auth (MCP + Hermes support it) | If exposed beyond own agents |
| mTLS | Strong mutual identity | High-security only |

Shape: a `api_keys` table `{key_hash, agent_name, created, revoked, rate_limit}`.
`BearerAuthMiddleware` swaps its `compare_digest`-against-one-env-var for a hashed
lookup. **Requirements that come with keys:** hashed at rest (store the hash, never
the key), transmitted only over TLS, rotatable and revocable without a redeploy.

### TLS / ingress

Terminate TLS **at the platform, not in the app** — a load balancer / ingress /
gateway (AWS ALB + ACM, Azure Application Gateway or Container Apps ingress, or
Cloudflare/Caddy in front) with a managed, auto-renewing cert, forwarding plain
HTTP to the container. The app stays HTTP internally. `mkcert` was a LAN-only
stopgap and drops out entirely. Net effect: HTTPS is a config line, not app code.

### MCP-specific wrinkle: session mode

Streamable-HTTP MCP can be **stateful** (session IDs — the "session manager
started" log line) or **stateless**. Stateful sessions behind a load balancer need
sticky routing; clean horizontal scaling wants FastMCP's `stateless_http=True`.
Decide this when moving past one replica — it's easy to miss because one instance
hides the problem.

### Deployment platform (AWS / Azure undecided)

Both clouds are the same shape; the existing `Dockerfile` is the portable asset:

| Need | AWS | Azure |
|---|---|---|
| Run the container | ECS/Fargate or App Runner | Container Apps |
| Job state | RDS for PostgreSQL | Azure Database for PostgreSQL |
| Queue (swarm rung) | SQS | Service Bus / Storage Queues |
| Secrets | Secrets Manager | Key Vault |
| TLS / ingress | ALB + ACM | Container Apps ingress / App Gateway |
| Scheduled daily call | EventBridge Scheduler | Logic Apps / Scheduler |

Pick one and don't abstract over both — portability lives in the container, not in
a cloud-agnostic layer.

---

## Recommended incremental path

Don't build the swarm. ~80% of the learning and value is in standing up the
single-customer deployment and operating it well:

1. **Externalize state to Postgres** (server reads/writes Postgres; `_mcp_jobs`
   demoted to a cache). This alone removes the single-instance trap.
2. **Containerized deploy** to one cloud service, TLS at the ingress, secrets in a
   vault, **per-agent API keys**.
3. **Wire the daily call** — Hermes (or a cloud scheduler) hits `start_research`
   daily, polls, retrieves the report.
4. **Operate it** per [reference/operations.md](../reference/operations.md): one
   alert when the daily run fails, tested backup/restore, one runbook.

Only when a real swarm appears: add the queue + worker pool, per-agent quotas, a
paid search API (DDG will rate-limit hard at scale — see [0001](0001-source-router.md)),
retries, and orphan-job reaping.

## Open questions

- Are `sources` worth persisting durably, or is best-effort (current-session only)
  acceptable for hosted use?
- Replace the hand-rolled `_init_db` ALTER-TABLE migration with a real migration
  tool (Alembic) now, or when the schema first changes under load?
- Does the daily report run *through* the MCP tool (Hermes drives it) or via a
  direct internal scheduler that bypasses MCP? (The former exercises the real path.)
- One container image with `--worker` / server entrypoints, or two images?
- At what point does stateful→stateless MCP session mode actually force itself?

## Prior art

Twelve-Factor App; the web-server-vs-worker split (Sidekiq/Celery/Arq); managed
Postgres as default durable store; `pgvector` for later semantic features; MCP
authorization spec (OAuth resource/authorization server); cloud-native queues
(SQS, Service Bus) and schedulers (EventBridge, Logic Apps).
