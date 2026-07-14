# Candidate topic inventory — corpus eval suite

**Raw material, not questions.** This is a map of *askable facts and where their
answers live*, organized by tier, with more candidates than slots so you select
and phrase. The questions and gold answers are yours to write — this just saves
you the codebase-spelunking so you can spend your effort on phrasing and judgment.

> **Scope: the corpus is frozen at `9b8b08f` — the *pre-RAG* repo.** It has the
> **6-node** pipeline (orchestrator, searcher, reader, critic, refiner, writer) and
> **no** `corpus_retriever`, no `retrieval` flag, no `llm/embeddings.py`, no
> `scripts/ingest_corpus.py`, no `corpus_chunks` table. Don't ask about any of
> that — those files don't exist in the corpus. (In fact, "how does Auspex's RAG
> retrieval work?" is a *legitimate T4 trap* against this commit.)

## Subsystem map (where things live at `9b8b08f`)

| Subsystem | Key files |
|---|---|
| Graph / pipeline | `graph/graph_builder.py`, `graph/state.py`, `graph/edges.py`, `agents/*.py` |
| LLM factory | `llm/ollama_client.py` (`get_llm`, `PROVIDERS`), `llm/contract.py` |
| Web app (SSE) | `app.py`, `frontend/`, `main.py` |
| MCP server | `auspex/mcp_server/server.py`, `auspex/mcp_server/__main__.py` |
| Job store / durability | `alembic/versions/*`, `app.py` (SQLite), `auspex/mcp_server/server.py` (Postgres) |
| Durable dispatch | Cloud Tasks in `server.py`, `infra/cloudtasks.tf` |
| Tools | `tools/web_search.py`, `tools/web_scraper.py` |
| Infra (IaC) | `infra/*.tf`, `infra/ARCHITECTURE.md` |
| Deploy | `Dockerfile`, `deploy/entrypoint-mcp.sh`, `.github/workflows/*.yml` |
| Decisions | `docs/adr/000{1..5}-*.md` |
| Proposals (undecided) | `docs/proposals/000{1..3}-*.md` |

---

## T1 — factual lookup (need 8; ~14 candidates)

Single-file facts. Answer grounds in one (occasionally two) file.

1. **MCP auth scheme** — bearer token via `AUSPEX_MCP_TOKEN`; unauth warning when unset. → `auspex/mcp_server/__main__.py`
2. **MCP tools exposed** — `start_research` / `get_research_status` / `get_research_report`. → `auspex/mcp_server/server.py`
3. **Default `max_iterations`** and the ceiling. → `app.py` (`MAX_ITERATIONS_DEFAULT/_CEILING`) or `auspex/mcp_server/server.py`
4. **Supported LLM providers** — ollama / huggingface / anthropic / nous / openai_compatible. → `llm/ollama_client.py` (`PROVIDERS`)
5. **Web search backend** — DuckDuckGo via `ddgs`. → `tools/web_search.py`
6. **Scrape stack** — requests + BeautifulSoup + markdownify. → `tools/web_scraper.py`
7. **Citation format contract** — `[Source](url)` + the link regex. → `llm/contract.py`
8. **Critic verdict tokens** — `PASSED` / `FAILED` / `MISSING:`. → `llm/contract.py`
9. **Reader concurrency** — `ThreadPoolExecutor(max_workers=3)`. → `agents/reader.py`
10. **Cloud Tasks dispatch deadline** — `TASK_DISPATCH_DEADLINE_SECONDS`, default 1800. → `auspex/mcp_server/server.py`
11. **Python versions in CI**. → `.github/workflows/test.yml`
12. **Ruff line-length / lint rules**. → `pyproject.toml`
13. **Web-app job store** — SQLite `jobs.db`. → `app.py`
14. **MCP HTTP vs stdio modes** and default port. → `auspex/mcp_server/__main__.py`

## T2 — multi-file synthesis (need 8; ~10 candidates)

Answer must assemble across files. List the full `grounding_files` set.

1. **Job lifecycle, web path** — HTTP submit → graph → SSE events → SQLite. → `app.py`, `graph/graph_builder.py`, `agents/*`
2. **Job lifecycle, MCP path** — `start_research` → Cloud Tasks enqueue → worker → Postgres. → `auspex/mcp_server/server.py`, `infra/cloudtasks.tf`
3. **The critique→refine loop** — how a FAILED critique routes back and what caps it. → `agents/critic.py`, `graph/edges.py`, `graph/graph_builder.py`, `agents/refiner.py`
4. **Provider selection flow** — env → `get_llm` → every agent, and how reports report the model. → `llm/ollama_client.py`, `agents/*`, `evals/adapter.py`
5. **Citation pipeline end-to-end** — prompt hint ↔ parser ↔ writer ↔ `citation_count` metric. → `llm/contract.py`, `prompts/writer.txt`, `agents/writer.py`, `app.py`
6. **Status reads after the worker split** — how live node/iteration is read from Postgres. → `auspex/mcp_server/server.py`, `alembic/versions/0002_*`
7. **Deploy path** — push → GitHub Actions → HF Spaces / Cloud Run. → `.github/workflows/*.yml`, `Dockerfile`, `infra/cloudrun.tf`
8. **State contract** — how a field written by one node reaches another (reducers). → `graph/state.py`, `agents/*`
9. **Secrets flow** — tfvars/Secret Manager → Cloud Run env → `get_llm`. → `infra/secrets.tf`, `infra/cloudrun.tf`, `llm/ollama_client.py`
10. **Frontend↔backend node contract** — `NODE_ORDER` / SSE events → spirit UI. → `app.py`, `frontend/`

## T3 — design rationale (need 7; gold lives in the ADRs)

Ask *why*. Gold answer comes from the decision record — cite the ADR.

1. **Why Cloud Tasks over in-process background tasks** → `docs/adr/0005-worker-split-cloud-tasks.md`
2. **Why Postgres over SQLite for the MCP job store** → `docs/adr/0004-host-mcp-server-on-aws-postgres.md`
3. **Why SQLite for the web-app job persistence** → `docs/adr/0003-sqlite-job-persistence.md`
4. **Why FastAPI over Streamlit** → `docs/adr/0001-fastapi-over-streamlit.md`
5. **Why TypedDict for state (not dataclass/Pydantic)** → `docs/adr/0002-typeddict-for-state.md`
6. **Why raw-SQL Alembic migrations (no ORM)** → `docs/adr/0004-*` + migration file headers
7. **Why the Cloud Tasks dispatch deadline is pinned** (avoid duplicate runs on retry) → `auspex/mcp_server/server.py` comments + `docs/adr/0005-*`
8. **Why the `get_llm` factory + `PROVIDERS` registry** (single source of truth, no drift) → `llm/ollama_client.py` docstring, `docs/reference/conventions.md`

> Note: `docs/proposals/*` are **undecided** forward proposals, not decisions.
> Don't use them as rationale gold — a correct answer about a proposal is "this is
> proposed, not implemented," which is more of a trap than a rationale.

## T4 — traps (need 2; verified absent at `9b8b08f`)

Correct answer = "the corpus contains no such thing." Leave `grounding_files`
empty; score on the rubric (refusing to fabricate).

**Clean (zero mentions in the corpus):**
- **Redis caching layer** (the plan's example) — `redis`: 0 files
- **Kafka / RabbitMQ message queue** — 0 files (durable dispatch is Cloud Tasks)
- **GraphQL API** — 0 files (it's REST + SSE)
- **Memcached** — 0 files
- **RAG / corpus / pgvector retrieval** — absent at this commit (added later); a neat
  self-referential trap, though you may find it too meta.

**Soft (mentioned only incidentally — usable, but word the gold carefully):**
- **WebSocket streaming** — the app streams via **SSE**; the only `websocket` hit is
  an incidental ASGI-scope comment in `server.py`. Gold should note SSE ≠ websockets.
- **Celery / Sidekiq workers** — named only as an *analogy* in `docs/proposals/0002`;
  actual dispatch is Cloud Tasks.
- **OAuth2/OIDC login** — only a *proposed future* option in `docs/proposals/0002`;
  current auth is the bearer token.

**Do NOT use as a trap:** rate limiting (`rate.limit` appears 5× — it's discussed as
a deferred/future item, so "absent" would be wrong).
