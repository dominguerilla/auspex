---
last_verified: 2026-06-12
sources: [graph/graph_builder.py, graph/state.py, graph/edges.py, agents/, llm/ollama_client.py, llm/contract.py, tools/, app.py, auspex/mcp_server/server.py, prompts/]
owner: Carlos
status: draft
---

# Architecture

## Overview

Auspex is a **LangGraph `StateGraph`** pipeline. A single shared dict (`ResearchState`) flows through six agent nodes; each node reads from and writes back to that dict. The graph is compiled once at startup (`build_graph()` in `graph/graph_builder.py`) and reused for every research run.

Three entrypoints drive the same graph:

| Entrypoint | Invocation | Output |
|---|---|---|
| `main.py` | `graph.invoke(initial_state)` (synchronous) | Markdown file written to `output/` |
| `app.py` | `graph.astream(initial_state)` (async) | SSE events → React frontend; completed job stored in `jobs.db` |
| `auspex/mcp_server/` | `graph.astream(initial_state)` (async, background task) | MCP tool responses over stdio; completed job stored in `jobs.db` |

---

## Pipeline graph

```
START
  │
  ▼
orchestrator  ──────────────────────────────────────────────────►  searcher
                                                                        │
                                                                        ▼
                                                                      reader
                                                                        │
                                                                        ▼
                                                                      critic
                                                                        │
                              should_revise_or_write(state)  ◄──────────┘
                                        │
                    ┌───────────────────┴───────────────────────┐
                    │ critique.passed == False                   │ critique.passed == True
                    │ AND iteration < max_iterations             │ OR iteration >= max_iterations
                    ▼                                            ▼
                 refiner ───────────────────────────►         writer
                 (replaces search_queries)                        │
                                                                  ▼
                                                                 END
```

Source: `graph/graph_builder.py:42-73`, routing logic: `graph/edges.py:27-42`

---

## Agent table

| Agent | Function | Reads | Writes |
|---|---|---|---|
| `orchestrator` | `agents/orchestrator.py:run_orchestrator` | `research_question` | `search_queries`, `messages` |
| `searcher` | `agents/searcher.py:run_searcher` | `search_queries` | `search_results` |
| `reader` | `agents/reader.py:run_reader` | `search_results`, `research_question` | `sources` |
| `critic` | `agents/critic.py:run_critic` | `sources`, `research_question`, `iteration` | `critique`, `iteration` |
| `refiner` | `agents/refiner.py:run_refiner` | `critique` (`missing_topics`, `feedback`), `research_question` | `search_queries` |
| `writer` | `agents/writer.py:run_writer` | `research_question`, `sources`, `critique` | `final_report` |

---

## State schema (`graph/state.py`)

```python
class ResearchState(TypedDict):
    # Set once at invocation, never mutated
    research_question: str
    max_iterations: int

    # Orchestrator / refiner writes; searcher reads
    search_queries: List[str]

    # Critic increments each loop; edges.py reads to cap loops
    iteration: int

    # Searcher writes (last-write-wins)
    search_results: List[SearchResult]   # {title, url, snippet}

    # Reader writes (last-write-wins)
    sources: List[ScrapedSource]         # {url, summary, raw_length}

    # Critic writes; edges.py reads .passed
    critique: Optional[CritiqueResult]  # {passed, feedback, missing_topics}

    # Writer writes; main.py / app.py reads
    final_report: Optional[str]

    # Append-only debug trace (add_messages reducer)
    messages: Annotated[List[BaseMessage], add_messages]
```

**Reducer rules** (source: `graph/state.py:35-43`):
- `messages` — `add_messages` reducer: each agent's `return {"messages": [...]}` *appends*, never replaces.
- All other fields — default (last-write-wins): the most recent node write is what the next node sees.

---

## LLM factory (`llm/ollama_client.py`)

`get_llm(temperature)` is the single LLM constructor. Every agent calls it; no agent imports `ChatOllama`, `ChatHuggingFace`, or `ChatOpenAI` directly. Provider selection is driven by `LLM_PROVIDER` env var at call time.

| `LLM_PROVIDER` | Returns | Key env vars |
|---|---|---|
| `ollama` (default) | `ChatOllama` | `OLLAMA_BASE_URL`, `OLLAMA_MODEL` |
| `huggingface` | `ChatHuggingFace` wrapping `HuggingFaceEndpoint` | `HF_TOKEN`, `HF_MODEL` |
| `nous` | `ChatOpenAI` against `portal.nousresearch.com/v1` | `NOUS_API_KEY`, `NOUS_MODEL` |
| `openai_compatible` | `ChatOpenAI` against any OpenAI-compatible endpoint | `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL` |

All implement `BaseChatModel`; agents call `llm.invoke([HumanMessage(...)])` regardless of provider.

**Provider registry (`PROVIDERS`).** Provider metadata — label, the env var that overrides the model, and the default model — lives in a single `PROVIDERS` dict (`llm/ollama_client.py`). Both `get_llm()` (construction) and `describe_llm()` (reporting) read it, and `evals/adapter.py` imports `describe_llm()`, so the model a run *reports* can't drift from the model it *uses*. The `openai_compatible` provider is the extension point: most new OpenAI-compatible backends (Together, Fireworks, OpenRouter, vLLM, …) are reachable via env vars alone, with no new code branch.

`describe_llm()` returns the same provider/model the next `get_llm()` call would construct — consumed by the FastAPI `/config` endpoint and by the eval adapter's `agent_model` label.

---

## LLM / parser contract (`llm/contract.py`)

Single source of truth tying prompt literals to Python parsers. (source: `llm/contract.py`)

| Constant | Value | Used by |
|---|---|---|
| `CITATION_FORMAT_HINT` | `"[Source](url)"` | Injected into `prompts/writer.txt`; `app.py` counts citations via `CITATION_LINK_RE` |
| `CITATION_LINK_RE` | `re.compile(r"\[Source\]\(https?://...\)")` | `app.py:144` — citation count in writer payload |
| `CRITIC_PASS` | `"PASSED"` | `prompts/critic.txt`; parsed by `agents/critic.py` |
| `CRITIC_FAIL` | `"FAILED"` | same |
| `CRITIC_MISSING_PREFIX` | `"MISSING:"` | parsed by `agents/critic.py` to extract `missing_topics` |

**Silent failure mode:** changing a prompt literal without updating the matching parser constant (or vice versa) produces no error — citations silently count 0, or every critique defaults to FAILED.

---

## Prompts (`prompts/`)

Plain `.txt` files with Python `.format()` placeholders. Each agent loads its own prompt file at call time via `Path(__file__).parent.parent / "prompts" / "<name>.txt"`. Placeholder names must exactly match what the agent passes to `.format(...)`.

| File | Agent | Key placeholders |
|---|---|---|
| `orchestrator.txt` | orchestrator | `research_question` |
| `searcher.txt` | searcher | `queries` (inferred) |
| `reader.txt` | reader | `research_question`, `url`, `content` (inferred) |
| `critic.txt` | critic | `research_question`, `sources` (inferred) |
| `refiner.txt` | refiner | `research_question`, `feedback`, `missing_topics` (`agents/refiner.py:49-53`) |
| `writer.txt` | writer | `research_question`, `sources`, `critique` (inferred) |

---

## Tools (`tools/`)

Thin wrappers with no state. Both degrade gracefully on error (return `[]` / `""`) rather than raising.

| Module | Function | Input | Output | Notes |
|---|---|---|---|---|
| `tools/web_search.py` | `web_search(queries)` | `List[str]` | `List[SearchResult]` | DuckDuckGo via `ddgs`; deduplicates by URL; degrades to `[]` on 429 |
| `tools/web_scraper.py` | `scrape_url(url)` | `str` | `str` (markdown) | BeautifulSoup + markdownify; returns `""` on 403/429/timeout |

---

## FastAPI server / frontend contract (`app.py`)

The server streams `node_complete` SSE events after each node finishes, then a final `complete` (or `error_event`) event. The frontend uses `NODE_ORDER` (defined at `app.py:49`) to map events to its UI positions:

```python
NODE_ORDER = ["orchestrator", "searcher", "reader", "critic", "refiner", "writer"]
```

Each `node_complete` event carries a `payload` built by `build_node_payload(node_name, delta)` (`app.py:112-146`). Per-node payload fields:

| Node | Extra fields |
|---|---|
| orchestrator / refiner | `queries: List[str]` |
| searcher | `results_count`, `urls` |
| reader | `sources_count`, `total_raw_kb`, `sources[{url, summary_first_line}]` |
| critic | `passed`, `feedback`, `missing_topics` |
| writer | `word_count`, `citation_count` |

**Shareable URLs:** completed jobs are stored in `jobs.db` (SQLite, `app.py:54-78`). The `/r/{job_id}` route returns the same `prototype.html`; the frontend reads the job snapshot from `GET /research/{job_id}`. The SQLite file is on the container's ephemeral disk — wiped on every HF Spaces redeploy.

---

## MCP Server (`auspex/mcp_server/`)

A third entrypoint that exposes the pipeline as MCP tools (`start_research`, `get_research_status`, `get_research_report`) and a resource (`research://{job_id}`) for Claude Desktop and other MCP clients. Launched via `python -m auspex.mcp_server` (stdio transport).

Design: `start_research` enqueues a job via `asyncio.create_task()` and returns immediately; clients poll `get_research_status`. The server holds its own in-memory job dict (`_mcp_jobs`) and shares `jobs.db` for persistence on completion. It imports `build_graph()` directly — it does not import `app.py`.

See [docs/mcp.md](../mcp.md) for client configuration and tool reference.

---

## Evals (`evals/`)

A separate evaluation harness built on `assay`. It wraps `graph.invoke(state)` through `evals/adapter.py` and scores outputs with programmatic scorers (`MustMention`, `MustNotMention`, `MinSources` in `evals/scorers.py`) plus an optional Anthropic LLM judge. Cases live in `evals/cases/*.jsonl`. Results are written to `evals/runs/<run_id>/`. See [evals/README.md](../../evals/README.md) for full details.
