---
last_verified: 2026-06-12
sources: [requirements.txt, .env.example, Dockerfile, .github/workflows/deploy-hf-spaces.yml, evals/requirements.txt]
owner: Carlos
status: draft
---

# Setup

All commands verified against the repo at commit `5c59f7e`. Run them in order; each step depends on the previous one.

---

## Prerequisites

- **Python 3.10+** (CI tests 3.10 and 3.12; Dockerfile uses 3.11-slim)
- **Ollama** — only needed for `LLM_PROVIDER=ollama` (local dev default). Install from https://ollama.com then pull the model:
  ```sh
  ollama pull qwen2.5:3b
  ```
- **HuggingFace account** — only needed for `LLM_PROVIDER=huggingface`. Create an access token at https://huggingface.co/settings/tokens.

---

## Local development

### 1. Clone and create a virtual environment

```sh
git clone <repo-url>
cd auspex
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
```

### 2. Install dependencies

```sh
pip install -r requirements.txt
```

### 3. Configure environment

```sh
cp .env.example .env
```

Then edit `.env`. Choose **one** provider block:

**Ollama (local, default):**
```
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=qwen2.5:3b
```

**HuggingFace (cloud):**
```
LLM_PROVIDER=huggingface
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxx
HF_MODEL=meta-llama/Llama-3.1-8B-Instruct
```

Optional — LangSmith tracing:
```
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=<your key>
LANGCHAIN_PROJECT=auspex
```

### 4. Verify the setup

```sh
# Run tests (no LLM or network needed — all mocked)
pytest

# Run the CLI with a simple question
python main.py "What is LangGraph?"
```

A Markdown report will be written to `output/<timestamp>_what_is_langgraph_.md`.

### 5. Run the web UI

```sh
uvicorn app:app --reload --port 7860
```

Open http://localhost:7860. The frontend is served from `frontend/` as static files.

### 6. Run the MCP server (optional)

```sh
python -m auspex.mcp_server
```

Exposes `start_research`, `get_research_status`, and `get_research_report` as MCP tools over stdio. See [docs/mcp.md](../mcp.md) for Claude Desktop configuration.

---

## Evaluation suite

The eval suite requires an additional install on top of the base dependencies:

```sh
pip install -r evals/requirements.txt
```

To use the LLM judge (Anthropic), also set:
```sh
export ANTHROPIC_API_KEY=<your key>
```

Run the full suite:
```sh
python -m evals.run                        # full suite (12 cases)
python -m evals.run --no-judge             # programmatic scorers only (no Anthropic key needed)
python -m evals.run --concurrency 1        # serialized (kinder to DDG + Ollama)
python -m evals.run --dataset evals/cases/humanities.jsonl  # humanities cases only
```

Results land in `evals/runs/<run_id>/` as JSON and a self-contained HTML report.

---

## Docker (local)

```sh
docker build -t auspex .
docker run -p 7860:7860 \
  -e LLM_PROVIDER=huggingface \
  -e HF_TOKEN=<your token> \
  -e HF_MODEL=Qwen/Qwen2.5-7B-Instruct \
  auspex
```

The Dockerfile hard-codes `LLM_PROVIDER=huggingface` and `HF_MODEL=Qwen/Qwen2.5-7B-Instruct` (source: `Dockerfile:7-9`); pass `-e` overrides to change them.

---

## Hugging Face Spaces deployment

Deployment is automated: every push to `master` triggers `.github/workflows/deploy-hf-spaces.yml`, which force-pushes to `huggingface.co/spaces/c-dom/auspex` (`main` branch).

**Required Space secret** (set in the Space's *Settings → Variables and secrets*):

| Secret | Value |
|---|---|
| `HF_TOKEN` | A HuggingFace access token with Inference API read access |

Override the default model via Space variables (`HF_MODEL=<model-id>`).

**Caveats:**
- `jobs.db` is on the container's ephemeral filesystem — wiped on every redeploy.
- The Space sleeps after ~48 h of no traffic; the first request after wakeup takes ~30 s.
