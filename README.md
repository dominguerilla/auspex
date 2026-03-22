# Multi-Agent Research Assistant

A portfolio-grade agentic system built with **LangGraph** and **Ollama** that researches topics by orchestrating a graph of specialised agents.

## Architecture

```
START → [orchestrator] → [searcher] → [reader] → [critic]
                                          ↑            |
                                          |    critique.passed == False
                                          |    AND iteration < max_iterations
                                          └────────────┘
                                                        |
                                              critique.passed == True
                                              OR iteration >= max_iterations
                                                        ↓
                                                   [writer] → END
```

| Agent | Role |
|---|---|
| **orchestrator** | Generates diverse search queries from the research question |
| **searcher** | Executes queries via DuckDuckGo, deduplicates by URL |
| **reader** | Scrapes each URL, summarises content with an LLM |
| **critic** | Evaluates coverage; passes or requests another search loop |
| **writer** | Assembles the final Markdown report |

## Setup

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — set OLLAMA_MODEL=qwen2.5:3b (or qwen2.5:7b for better quality)

# 4. Pull the model (if not already available)
ollama pull qwen2.5:3b
```

## Usage

```bash
python main.py "What are the tradeoffs of Rust vs Go for CLI tools?"
python main.py "How does transformer attention work?" --max-iterations 3
python main.py "Best practices for Kubernetes networking" --output-dir reports/
```

Reports are written to `output/<timestamp>_<slug>.md`.

## Testing

There is no external service dependency for tests — the LLM and network calls are mocked via `unittest.mock`.

```bash
# Run all tests
pytest

# Run a specific test file
pytest tests/test_orchestrator.py

# Run with verbose output
pytest -v

# Stop on first failure
pytest -x
```

Tests live in `tests/` and use fixtures from `tests/conftest.py` — `mock_llm` (a `MagicMock` ChatOllama) and `base_state` (a zeroed `ResearchState` dict).

## Build Order (Learning Path)

1. **Phase 1** — `agents/orchestrator.py`: implement query parsing → test with a REPL script
2. **Phase 2** — `tools/web_search.py` + `tools/web_scraper.py` + `agents/searcher.py` + `agents/reader.py` + wire 3 nodes in `graph/graph_builder.py`
3. **Phase 3** — `agents/critic.py` + `graph/edges.py` + conditional edge in `graph_builder.py`
4. **Phase 4** — `agents/writer.py` + `main.py` → run end-to-end

See `LEARNING.md` for concept explanations.

## Switching Models

Change `OLLAMA_MODEL` in `.env` — no code changes required:

- `qwen2.5:3b` — fast, good for development
- `qwen2.5:7b` — better quality for demos
