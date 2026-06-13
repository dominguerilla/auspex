---
last_verified: 2026-06-12
sources: [main.py, app.py, auspex/mcp_server/server.py, graph/graph_builder.py, graph/state.py, llm/ollama_client.py, llm/contract.py]
owner: Carlos
status: draft
---

# Auspex — Start Here

Auspex is a LangGraph multi-agent research pipeline that answers a question by routing a shared `ResearchState` dict through six agent nodes — orchestrator, searcher, reader, critic, refiner, writer. It has three entrypoints: a CLI (`main.py`) that writes a Markdown report to disk, a FastAPI server (`app.py`) that streams per-node progress to a React frontend over SSE and persists completed jobs in SQLite, and an MCP server (`auspex/mcp_server/`) that exposes the pipeline as tools for Claude Desktop and other MCP clients. All three call the same `build_graph()` function.

## Doc map

| Topic | Doc |
|---|---|
| This file (start here) | `AGENTS.md` |
| Full doc index / outage map | [docs/README.md](docs/README.md) |
| System architecture | [docs/reference/architecture.md](docs/reference/architecture.md) |
| Local + cloud setup | [docs/reference/setup.md](docs/reference/setup.md) |
| Conventions & style | [docs/reference/conventions.md](docs/reference/conventions.md) |
| Troubleshooting | [docs/reference/troubleshooting.md](docs/reference/troubleshooting.md) |
| LangGraph concepts & vocabulary | [docs/reference/LEARNING.md](docs/reference/LEARNING.md) |
| MCP server (Claude Desktop) | [docs/mcp.md](docs/mcp.md) |
| Evaluation suite | [evals/README.md](evals/README.md) |
| Architecture decisions (decided) | [docs/adr/](docs/adr/) |
| Forward proposals (undecided) | [docs/proposals/](docs/proposals/) |
| Task playbooks | [docs/skills/](docs/skills/) |

## Build / test / run

```sh
# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
cp .env.example .env               # then edit .env — see docs/reference/setup.md

# CLI (synchronous, writes report to output/)
python main.py "Your research question"
python main.py "Your question" --max-iterations 3 --output-dir reports/

# Web UI (FastAPI + SSE frontend on http://localhost:7860)
uvicorn app:app --reload --port 7860

# Tests (all mocked — no LLM or network required)
pytest
pytest -x          # stop on first failure
pytest -v          # verbose

# Lint
ruff check .
```

## Rules of the road

**Contract files — change with extra care:**

- [`graph/state.py`](graph/state.py) — defines `ResearchState` and all sub-types (`SearchResult`, `ScrapedSource`, `CritiqueResult`). Renaming a field silently breaks every agent that reads it.
- [`llm/contract.py`](llm/contract.py) — ties prompt literal strings to Python parsers (`CITATION_FORMAT_HINT`, `CRITIC_PASS/FAIL`, `MISSING_PREFIX`). Changing either side alone causes silent failures (citations count 0, every critique defaults to FAILED).
- [`graph/edges.py`](graph/edges.py) — `should_revise_or_write()` return values must exactly match the keys in the `add_conditional_edges` mapping in `graph/graph_builder.py`.

**Structural rules:**

- Always construct LLMs via `llm/ollama_client.py:get_llm()` — never build `ChatOllama` or `ChatHuggingFace` directly inside agents.
- Prompts live in `prompts/*.txt` as plain text with Python `.format()` placeholders; placeholder names must match what each agent passes.
- Agent functions have the signature `(state: ResearchState) -> dict` and return only the keys they write.
- Tests mock the LLM and all network calls — integration testing requires running `main.py` manually.
- CI (`.github/workflows/test.yml`) runs ruff then pytest on Python 3.10 and 3.12 on every master push/PR. Both must pass before merging.

**Documentation rule:**

Any change to a source file listed in a doc's `sources:` frontmatter must be accompanied by an update to that doc in the same commit. After finishing a non-trivial change, run the `docs-evergreen` skill ([docs/skills/docs-evergreen/SKILL.md](docs/skills/docs-evergreen/SKILL.md)) to catch drift before closing the task. At minimum: update the relevant doc's prose and bump its `last_verified` date to today.
