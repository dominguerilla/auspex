# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set OLLAMA_MODEL (default: qwen2.5:3b)
ollama pull qwen2.5:3b
```

## Running

```bash
python main.py "Your research question here"
python main.py "Your question" --max-iterations 3 --output-dir reports/
```

There is no automated test suite. Test manually by running `main.py`.

## Architecture

This is a **LangGraph multi-agent research pipeline**. A `StateGraph` routes a `ResearchState` dict through five agent nodes, each reading from and writing back to shared state.

**Flow:**
```
START → orchestrator → searcher → reader → critic → (conditional) → writer → END
                                                 ↑___________________________|
                                         (loop if critique failed & iterations remain)
```

**State merge rules** (`graph/state.py`):
- `messages`: append-only via `add_messages` reducer
- All other fields: last-write-wins (default)

**Agents** (`agents/`): Each agent is a plain function `(state: ResearchState) -> dict` returning only the keys it writes.

| Agent | Reads | Writes |
|-------|-------|--------|
| `orchestrator` | `research_question` | `search_queries`, `messages` |
| `searcher` | `search_queries` | `search_results` |
| `reader` | `search_results`, `research_question` | `sources` |
| `critic` | `sources`, `research_question`, `iteration` | `critique`, `iteration` |
| `writer` | `research_question`, `sources`, `critique` | `final_report` |

**Routing** (`graph/edges.py`): `should_revise_or_write(state)` returns `"searcher"` or `"writer"` based on `critique.passed` and whether `iteration < max_iterations`.

**Tools** (`tools/`): Thin wrappers — `web_search.py` normalizes DuckDuckGo results to `{title, url, snippet}`; `web_scraper.py` fetches a URL and converts HTML to markdown via BeautifulSoup + markdownify.

**LLM** (`llm/ollama_client.py`): `get_llm(temperature)` is the single factory for `ChatOllama`. Model and base URL come from `.env`. Switch models by changing `OLLAMA_MODEL` — no code changes needed.

**Prompts** (`prompts/`): Plain `.txt` files with Python `.format()` placeholders. Each agent loads its own prompt at call time.

## Implementation Status

Many components have `# TODO` stubs. Fully implemented: `state.py`, `ollama_client.py`. Partially implemented: `orchestrator.py`, `graph_builder.py`, `main.py`. Not yet started: all other agents, tools, `edges.py`.

`LEARNING.md` contains concept explanations, vocabulary, and the intended design for each TODO.
