# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set LLM_PROVIDER and model vars
ollama pull qwen2.5:3b  # only needed for LLM_PROVIDER=ollama
```

## Running

```bash
python main.py "Your research question here"
python main.py "Your question" --max-iterations 3 --output-dir reports/
```

There is also a Streamlit web UI: `streamlit run streamlit_app.py`.

## Testing

```bash
pytest          # run all tests
pytest -x       # stop on first failure
```

Tests live in `tests/` and mock the LLM and network calls via `unittest.mock`. Test manually with `main.py` for end-to-end validation.

## Architecture

This is a **LangGraph multi-agent research pipeline**. A `StateGraph` routes a `ResearchState` dict through five agent nodes, each reading from and writing back to shared state.

**Flow:**
```
START → orchestrator → searcher → reader → critic → (conditional) → writer → END
                          ↑___________________________|
                  (loop back to searcher if critique failed & iterations remain)
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

**LLM** (`llm/ollama_client.py`): `get_llm(temperature)` is the single factory. Supports two providers selected by `LLM_PROVIDER` env var: `ollama` (default, local via `ChatOllama`) and `huggingface` (cloud via HF Inference API). Switch models by changing env vars — no code changes needed.

**Prompts** (`prompts/`): Plain `.txt` files with Python `.format()` placeholders. Each agent loads its own prompt at call time.

## Implementation Status

All agents, tools, graph wiring, and `main.py` are implemented. One minor TODO remains in `agents/searcher.py`. `LEARNING.md` contains concept explanations and vocabulary for the patterns used.
