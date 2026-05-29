---
title: Multi-Agent Research Assistant
emoji: 🔍
colorFrom: blue
colorTo: purple
sdk: docker
app_port: 7860
pinned: false
short_description: LangGraph multi-agent research pipeline
tags:
  - langgraph
  - agents
  - research
---

# Multi-Agent Research Assistant

[![Tests](https://github.com/dominguerilla/research-agent/actions/workflows/test.yml/badge.svg)](https://github.com/dominguerilla/research-agent/actions/workflows/test.yml)
[![Try it on HF Spaces](https://img.shields.io/badge/%F0%9F%A4%97%20Hugging%20Face-Spaces-blue)](https://huggingface.co/spaces/c-dom/researcher)
[![GitHub](https://img.shields.io/badge/GitHub-Source-black?logo=github)](https://github.com/dominguerilla/research-agent)

An agentic system built with **LangGraph** and **Ollama/HuggingFace** that researches topics by orchestrating a graph of specialised agents.

## Architecture

```
START → [orchestrator] → [searcher] → [reader] → [critic]
                              ↑                        |
                              |    critique.passed == False
                              |    AND iteration < max_iterations
                              └────────────────────────┘
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

Requires **Python 3.10+**.

```bash
# 1. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — set LLM_PROVIDER (ollama or huggingface) and the relevant model vars
```

### Ollama (local, default)

```bash
ollama pull qwen2.5:3b
```

Set in `.env`:
```
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434   # default
OLLAMA_MODEL=qwen2.5:3b                 # or qwen2.5:7b for better quality
```

### HuggingFace (cloud / HF Spaces)

Set in `.env`:
```
LLM_PROVIDER=huggingface
HF_TOKEN=<your HF access token>
HF_MODEL=meta-llama/Llama-3.1-8B-Instruct   # any HF Inference API-compatible instruct model
```

Optionally enable [LangSmith](https://smith.langchain.com/) tracing:
```
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_key_here
LANGCHAIN_PROJECT=researcher
```

## Usage

```bash
python main.py "What are the tradeoffs of Rust vs Go for CLI tools?"
python main.py "How does transformer attention work?" --max-iterations 3
python main.py "Best practices for Kubernetes networking" --output-dir reports/
```

The CLI prints progress as it runs, then writes a Markdown report to `output/<timestamp>_<slug>.md` containing structured findings and inline source links.

### Web UI (FastAPI + single-flow frontend)

The deployed app is a FastAPI server (`app.py`) that drives the React single-flow
prototype in `frontend/`. Run it locally with:

```bash
uvicorn app:app --reload --port 7860
```

Then open <http://localhost:7860>. The flow:

1. Pose a question, choose max challenges, submit.
2. The Circle animates as each agent (orchestrator → searcher → reader → critic → optional refiner → writer) completes.
3. On completion, the report opens from the center of the Circle and can be shared via the `/r/{job_id}` URL.

The job runs server-side and persists across tab backgrounding / phone lock. Each
job's `job_id` is stored in `sessionStorage` so a refresh resumes the same job,
and the URL is rewritten to `/r/{job_id}` so the address bar is itself a shareable
link. Completed reports are persisted to `jobs.db` (SQLite on the container's
ephemeral disk) and stay available until the next redeployment.

## Deployment (HF Spaces, Docker SDK)

This Space is configured with `sdk: docker` (see the frontmatter above). HF
builds the `Dockerfile`, exposes port 7860, and routes traffic to FastAPI.

Required Space secrets (set in the Space's *Settings → Variables and secrets*):

| Secret | Value |
|---|---|
| `HF_TOKEN` | A Hugging Face access token with Inference API read access |

The Dockerfile pre-sets `LLM_PROVIDER=huggingface` and `HF_MODEL=Qwen/Qwen2.5-7B-Instruct`.
Override `HF_MODEL` via Space variables if you want to try a different model.

Notes:
- The container's filesystem is ephemeral on the free tier — `jobs.db` is wiped on every redeploy. The UI surfaces this in the "About this report" rail.
- The Space sleeps after ~48h of no traffic; the first request after sleep takes ~30s to warm up.

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

