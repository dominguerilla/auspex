---
last_verified: 2026-06-18
sources: [Dockerfile, deploy/entrypoint-mcp.sh, infra/, .github/workflows/test.yml, auspex/mcp_server/server.py, docs/adr/0004-host-mcp-server-on-aws-postgres.md, docs/adr/0005-worker-split-cloud-tasks.md]
owner: Carlos
status: draft
---

# Operations — Running Auspex as a Service

This is the **operational-readiness track**: the skills and tasks of running the
hosted MCP server as if a customer depended on it. It is a companion to the
architecture sketch in [proposals/0002-hosting-auspex.md](../proposals/0002-hosting-auspex.md).

The first hosted deployment is now **live on GCP Cloud Run** (one caller, a daily
report), so the rung-D boxes are largely checked. The remaining gaps are the
operational wrapper — a **tested restore**, the **one failure alert**, a **budget
alert**, and an **incident runbook** — not new features. This track exercises ~80%
of the muscles you'd need to run it for a paying customer, at near-zero blast radius.

**Maturity legend:** ☐ not started · ◐ partial · ☑ done.
The **"Rung"** column says when an item matters: **D** = needed for the daily-report
deployment, **S** = only matters at swarm / multi-customer scale.

---

## The mindset shift

Three things separate "I built a thing" from "someone relies on my thing":

1. **The MCP tool schema is now a contract.** Once Hermes (or a customer's agent)
   calls `start_research` / `get_research_status` / `get_research_report`, you can no
   longer rename them or change their output shape freely — a change silently breaks
   the caller. Treat the tool interface like the other contract files in
   [AGENTS.md](../../AGENTS.md), except the consumer is external.
2. **A backup means nothing until you've restored from it.** An untested backup is a
   hope. The skill is the *restore drill*, not the backup.
3. **You should know it's broken before the caller tells you.** That is almost the
   definition of running a service someone relies on. For the daily report it is
   one alert — but wiring it teaches the whole observability loop.

---

## 1. Deploy & reproduce

*Can you rebuild this identically, on purpose, every time?*

| | Item | Rung |
|---|---|---|
| ☑ | Containerized (`Dockerfile` + `deploy/entrypoint-mcp.sh` for the MCP server) | D |
| ☑ | Deployed to GCP Cloud Run as a long-running service (`terraform apply`) | D |
| ☑ | Infrastructure defined as code — Terraform in `infra/`, applied; remote state in GCS | D |
| ◐ | Config externalized (tfvars + Secret Manager, no prod values in the image); single env | D |
| ☐ | A staging environment that mirrors prod for testing changes | S |

**Skill:** containers, IaC, environment/config separation.

## 2. Secure

*Who can reach it, what can they do, and how do secrets stay secret?*

| | Item | Rung |
|---|---|---|
| ☑ | Bearer-token auth on the HTTP endpoint (`AUSPEX_MCP_TOKEN`) | D |
| ☐ | Per-agent API keys (hashed at rest, revocable) — see 0002 auth model | D |
| ☑ | TLS terminated at the ingress with a managed cert (Cloud Run) | D |
| ☑ | Secrets in a vault (Secret Manager), not `.env` on the host | D |
| ◐ | Network exposure scoped — DB private (Cloud SQL); HTTP endpoint public but bearer-gated | D |
| ☐ | Dependency vulnerability scanning in CI; a patch cadence | S |

**Skill:** authn/authz, TLS, secrets management, network policy, supply-chain hygiene.

## 3. Observe

*Can you tell it's healthy without a caller telling you?*

| | Item | Rung |
|---|---|---|
| ◐ | LLM tracing (LangSmith hooks already wired — see setup docs) | D |
| ◐ | Logs shipped to a queryable store (Cloud Logging, automatic) — not yet structured | D |
| ☐ | **One alert: the daily report failed → notify me** | D |
| ☐ | Core metrics: job success/failure, duration, (later) queue depth | S |
| ☐ | A dashboard you actually look at | S |

**Skill:** structured logging, metrics, tracing, alerting thresholds.

## 4. Stay up

*What happens when it breaks at 3am?*

| | Item | Rung |
|---|---|---|
| ◐ | Health probe — Cloud Run TCP startup probe on the port (no app `/health` route) | D |
| ☑ | Auto-restart on crash (Cloud Run restarts unhealthy instances) | D |
| ◐ | Failure modes: pipeline errors persist as `status=error`; Cloud Tasks retries 5xx; hung jobs bounded by the dispatch deadline | D |
| ☐ | A defined SLO (e.g. "daily report delivered by 8am, 95% of days") | S |
| ◐ | Stateless server + durable jobs make replicas a config change (`max_instances`) — see 0005 | S |

**Skill:** health checks, restart policy, failure-mode analysis, SLOs.

## 5. Protect data

*The state you cannot afford to lose.*

| | Item | Rung |
|---|---|---|
| ☑ | Job store on Cloud SQL Postgres, not SQLite (deployed — see 0004) | D |
| ☑ | Durable `sources` table (cross-run scrape cache + provenance) | D |
| ☑ | Alembic migrations replace the hand-rolled `_init_db` ALTER | D |
| ☑ | Automated backups enabled (Cloud SQL daily backups) | D |
| ☐ | **A restore actually tested** (delete-and-recover in a safe env) | D |
| ☐ | Retention policy for old jobs / reports | S |

**Skill:** backups + restore drills, migrations, data lifecycle.

## 6. Manage change

*How do you ship a change without breaking the caller?*

| | Item | Rung |
|---|---|---|
| ☑ | CI runs ruff + pytest (+ Postgres + Alembic) on every push (`.github/workflows/test.yml`) | D |
| ☐ | The MCP tool schema treated as a versioned contract; breaking changes avoided | D |
| ◐ | Rollback path — Cloud Run keeps revisions; re-apply a prior `image_tag` (not yet a one-command drill) | D |
| ☐ | Changes flow through staging before prod | S |
| ☐ | Deprecation process for tool-interface changes callers depend on | S |

**Skill:** CI/CD, interface versioning & backward compatibility, rollback discipline.

## 7. Control cost

*A service that runs daily and calls LLMs spends money continuously.*

| | Item | Rung |
|---|---|---|
| ◐ | Per-run cost: infra floor ~$8–10/mo (Cloud SQL) known; LLM ~$0 on the Nous free tier | D |
| ☐ | A budget alert so a loop or bug can't silently rack up spend | D |
| ☑ | Provider-in-cloud decided — cloud LLM API via `get_llm()` (Ollama rejected for hosting, 0004) | D |
| ☐ | Per-agent quotas / rate limits | S |
| ◐ | Right-sized: `db-f1-micro` + scale-to-zero Cloud Run; idle ≈ Cloud SQL only | S |

**Skill:** cost modeling, budget alerting, capacity right-sizing.

## 8. Respond to incidents

*When — not if — it breaks, how fast can you diagnose, and is it written down?*

| | Item | Rung |
|---|---|---|
| ☐ | A runbook: "the daily report didn't arrive — here's where I look" | D |
| ◐ | Logs to diagnose a failed run — Cloud Logging captures worker exceptions + the job `error` field | D |
| ☐ | A lightweight postmortem habit (what broke, why, what prevents recurrence) | S |
| ☐ | On-call / notification path that reaches you | S |

**Skill:** runbooks, production debugging, postmortems.

---

## What you already have going for you

Not starting from zero: a live Cloud Run deployment via Terraform, a CI/CD pipeline
(`.github/workflows/`), LangSmith tracing wired, bearer-auth + durable Cloud-Tasks
jobs on the MCP server, and — genuinely uncommon — a documentation discipline
([docs/skills/docs-evergreen](../skills/docs-evergreen/SKILL.md), `AGENTS.md`). The
gap to "customer-grade" is mostly the operational wrapper above, not new features.

## The first rung, concretely

One project that teaches the most per unit effort: **deploy the daily-report
version online and operate it like a customer depends on it.** Minimum set of
boxes to call rung 1 done:

- 1.2, 1.3 (deployed via IaC) · 2.2, 2.3, 2.4 (API keys, TLS, vault) ·
  3.2, 3.3 (logs + the one alert) · 4.1, 4.2 (health check + restart) ·
  5.1–5.5 (Postgres + sources + Alembic + tested backup) · 6.3 (rollback path) ·
  7.1, 7.2 (cost known + budgeted) · 8.1 (the runbook).

Everything marked **S** is the swarm rung — climb it only when real load arrives.
Because rung 1 externalizes state to Postgres and makes the server stateless, the
swarm rung is a scaling exercise, not a rewrite.
