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
- Persist `sources` (currently in-memory only) durably in a side table — see
  **Persisting sources** below. **Decided:** sources are worth keeping.

Once state is external and the server holds nothing job-specific in memory, the
server is **stateless** and horizontally scalable — the precondition for every
later step.

> **Storage clarification.** Postgres is the answer to *durable, concurrent job
> state*. A **vector DB is a different tool for a different problem** (semantic
> similarity), and is not part of this proposal. When query-dedup or a research
> knowledge base is wanted later, `pgvector` can ride on the same Postgres — no new
> system. Don't adopt vectors as a "more robust store"; adopt Postgres for that.

### Persisting sources

Today a source is `ScrapedSource = {url, summary, raw_length}` (`graph/state.py`),
produced by the reader node, returned once by `get_research_report`, then evicted.
Persisting them durably buys, in order of value:

- **Cross-run scrape cache.** The expensive work is the reader scraping *and
  LLM-summarizing* each URL. Within a run the searcher dedups by URL, but across
  runs the same page is re-scraped from scratch. A URL-keyed lookup lets the reader
  reuse a recent summary — saving tokens, latency, and DDG/scrape rate-limit budget.
- **Provenance / audit.** Once a job is evicted today, its report loses its evidence
  trail. Persisted sources keep "where did this claim come from?" answerable for any
  past report.
- **RAG substrate (deferred).** Embedding source summaries into an accumulating
  knowledge base (0001 + `pgvector`) is only possible if the sources aren't thrown
  away now.

Two kinds of dedup people conflate: **source-level** (don't re-scrape a URL — what
this table enables directly) vs **query-level** (don't re-run a near-identical
*question* — report caching, the embedding angle). This table gives the first and
is a prerequisite for the second.

Schema — map `ScrapedSource` across, add identity, job linkage, and a freshness
timestamp:

```sql
CREATE TABLE sources (
    id          BIGSERIAL    PRIMARY KEY,
    job_id      TEXT         NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    url         TEXT         NOT NULL,
    summary     TEXT         NOT NULL,   -- ScrapedSource.summary (LLM summary)
    raw_length  INTEGER      NOT NULL,   -- ScrapedSource.raw_length
    scraped_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
    -- deferred: content_hash TEXT (exact-dup detection),
    --           embedding VECTOR(768) (pgvector, RAG rung)
);
CREATE INDEX idx_sources_url ON sources(url);
CREATE INDEX idx_sources_job ON sources(job_id);
```

`ON DELETE CASCADE` cleans sources up with their job. The `url` index powers the
cache read:

```sql
SELECT summary, raw_length FROM sources
WHERE url = %s AND scraped_at > now() - interval '7 days'
ORDER BY scraped_at DESC LIMIT 1;
```

This keeps **one row per (job, url)**, preserving provenance with cache reuse via
the query above. Normalizing to a URL-keyed cache + a job↔source join is cleaner
for dedup but adds moving parts — start simple, normalize only if duplication hurts.
The two commented columns are the only RAG-specific additions, and `pgvector` adds
`embedding` without a new datastore.

### Migrations (Alembic)

**Decided:** adopt [Alembic](https://alembic.sqlalchemy.org/), the standard Python
schema-migration tool, in place of the hand-rolled `_init_db()` (`CREATE TABLE IF
NOT EXISTS` + try/except `ALTER TABLE`). Alembic represents the schema as an ordered
series of revision scripts, each with `upgrade()`/`downgrade()`, and records the
applied revision in an `alembic_version` table — so a fresh or old database reaches
the current schema deterministically.

Workflow:

```bash
alembic init alembic                          # scaffold (once)
alembic revision -m "create jobs and sources" # write a versioned script
alembic upgrade head                          # apply pending migrations
alembic downgrade -1                          # roll back one
```

A revision is plain code:

```python
def upgrade():
    op.create_table(
        "sources",
        sa.Column("id", sa.BigInteger, primary_key=True),
        sa.Column("job_id", sa.Text,
                  sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("raw_length", sa.Integer, nullable=False),
        sa.Column("scraped_at", sa.DateTime(timezone=True),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_sources_url", "sources", ["url"])

def downgrade():
    op.drop_index("idx_sources_url")
    op.drop_table("sources")
```

In Auspex: **init** = the first revision creates the `jobs` and `sources` tables
(`alembic upgrade head` on a fresh DB builds everything, retiring `_init_db`);
**update** = a new revision per schema change, applied by `alembic upgrade head` on
deploy. You need **not** adopt the full ORM — migrations can be raw SQL via
`op.execute(...)`, so the app keeps its raw queries and Alembic owns only schema
versioning. At the swarm rung, run migrations as a **single** step (one-shot job or
guarded entrypoint), never concurrently from every replica.

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

Two independent layers of "state" must each leave process memory to scale:
**application state** (job records → Postgres, above) and **MCP protocol session
state** (this section) — easy to conflate.

Streamable-HTTP MCP is session-oriented by default: `initialize` creates a session
held **in one replica's memory** (the "session manager started" / "Created new
transport with session ID" logs) and returns an `Mcp-Session-Id` the client echoes
on later requests, optionally over a long-lived SSE stream the server can push to.
Behind a load balancer with >1 replica, that demands **sticky routing** (pin each
session ID to its owning replica) — which unbalances load and dies with the replica.

`stateless_http=True` makes each request self-contained, so any replica serves any
request — at the cost of server-initiated messaging (push notifications, progress
events, resumability). **Decided: run stateless** — Auspex's tools are pure
request/response + polling, so nothing depends on push; the only thing lost is the
*stretch* "MCP progress notifications" idea, which polling already replaces. It's a
one-flag change; enable it when the hosted (multi-replica-capable) deployment is
built — harmless at single-instance, and one instance otherwise *hides* the
sticky-session requirement until you scale out.

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
3. **Wire the daily call** — a separate cron'd agent picks a topic, calls
   `start_research`, **polls** `get_research_status` (not a blind sleep) until
   `done`, retrieves the report, and delivers it via its own channels. Auspex stays
   a pure on-demand service with no scheduler of its own. The agent must handle
   `status == "error"` (surface the failure, don't deliver a broken report).
4. **Operate it** per [reference/operations.md](../reference/operations.md): one
   alert when the daily run fails, tested backup/restore, one runbook.

Only when a real swarm appears: add the queue + worker pool, per-agent quotas, a
paid search API (DDG will rate-limit hard at scale — see [0001](0001-source-router.md)),
retries, and orphan-job reaping.

## Resolved questions

- **Persist `sources` durably?** **Yes.** Worth it for the cross-run scrape cache,
  provenance, and as the RAG substrate — see **Persisting sources** for the schema.
- **Adopt Alembic, or keep the hand-rolled migration?** **Adopt Alembic** — see
  **Migrations (Alembic)**.
- **Daily report through the MCP tool or an internal scheduler?** **Through the
  tool.** A separate cron'd agent drives `start_research` → poll → retrieve; Auspex
  has no scheduler of its own (exercises the real auth/contract path).
- **One container image or two?** **One** for now — server and worker run as
  different entrypoints off the same image; they share the graph + DB layer and stay
  in lockstep. Two images pay off only once the server sheds the pipeline's deps
  (smaller/safer public image) or needs a different base (e.g. GPU worker) — both
  swarm-rung concerns.
- **`sources` table shape?** **One row per (job, url)** for now — provenance-
  preserving, with cross-run reuse via the `url` index query. Normalize to a
  URL-keyed cache + join table only if duplication measurably hurts.
- **MCP session mode?** **Run stateless** (`stateless_http=True`) — see
  **MCP-specific wrinkle: session mode**. One-flag change; nothing depends on push.
- **Alembic migration authoring — raw SQL or SQLAlchemy models?** **Raw SQL** for
  now (no ORM). Gives versioned/rollback-able migrations without a data-layer
  rewrite; `pgvector`/Postgres DDL stays direct. Not a one-way door — Alembic keeps
  its revision history when models are introduced later. Revisit SQLAlchemy +
  autogenerate when the schema grows past a handful of related tables or typed
  access starts paying off (the eval feature below is the likely trigger).

## Open questions

- Eval feature (below): the exact stored eval-case shape, dedicated `eval_runs` /
  `eval_scores` tables vs a serialized view over `jobs`+`sources`, and scoring a
  stored report without re-running the graph.

## Future feature: scheduled evaluation of past reports

Goal (not built now): trigger evaluations of stored reports via MCP on a schedule —
e.g. a cron'd agent calls a `start_evaluation(job_id)` tool, polls, retrieves
scores. **Does it change resolved decisions? Mostly no, and here's why:**

- **Session mode / Alembic-raw-SQL / external scheduler / one image** — unaffected,
  and *reinforced*: an eval run is just another async request/response job, driven
  by an external scheduler, behind additive MCP tools. Same patterns as research.
- **The one thing to bake in now (can't backfill):** persist the **eval inputs at
  write time**. Question, report, and sources are already covered by the resolved
  schema; add **`agent_model`** (the `describe_llm()` provider/model that produced
  the report — already the eval adapter's `agent_model` label) and timing to the
  `jobs` row, because a past run isn't fairly evaluable without knowing what made it,
  and you cannot recover it later.
- **Schema growth, not engine change:** evaluating adds `eval_runs` / `eval_scores`
  tables. Still fine as raw SQL, but this is precisely the "handful of related
  tables" point at which revisiting SQLAlchemy + autogenerate earns its cost.

Designed in [0003](0003-scheduled-evals.md); the scoring path reuses the existing
`evals/generate.py` + `evals/run.py --from-outputs` split, reading a stored run and
feeding `evals/scorers.py` directly, bypassing `graph.invoke` (no re-research).

## Prior art

Twelve-Factor App; the web-server-vs-worker split (Sidekiq/Celery/Arq); managed
Postgres as default durable store; `pgvector` for later semantic features; MCP
authorization spec (OAuth resource/authorization server); cloud-native queues
(SQS, Service Bus) and schedulers (EventBridge, Logic Apps).
