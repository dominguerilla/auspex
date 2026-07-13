---
last_verified: 2026-07-13
sources: [requirements.txt, .env.example, Dockerfile, .github/workflows/deploy-hf-spaces.yml, evals/requirements.txt, Makefile, docker-compose.yml, scripts/ingest_corpus.py, llm/embeddings.py]
owner: Carlos
status: draft
---

# Setup

Run the steps in order; each depends on the previous one. Most commands have a
`make` shortcut (see [Task runner](#task-runner-makefile) at the end) — the raw
commands here are the explanation, the Makefile is the convenience.

---

## Prerequisites

- **Python 3.10+** (CI tests 3.10 and 3.12; Dockerfile uses 3.11-slim)
- **Ollama** — only needed for `LLM_PROVIDER=ollama` (local dev default). Install from https://ollama.com then pull the model:
  ```sh
  ollama pull qwen2.5:3b
  ```
- **HuggingFace account** — only needed for `LLM_PROVIDER=huggingface`. Create an access token at https://huggingface.co/settings/tokens.
- **Docker** — only needed for the [corpus store](#corpus-store-rag-retrieval) (local Postgres + pgvector). Not required for the CLI, web UI, or tests.

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

## Corpus store (RAG retrieval)

The RAG retrieval experiment ingests the Auspex repo itself into a pgvector
store (`corpus_chunks`) so the pipeline can retrieve over its own source. This
is independent of the SQLite/Postgres **job** store above; it needs its own
local Postgres and an embedding model.

> **Run this from WSL2/Linux, not native Windows.** The ingestion script opens a
> `psycopg2` connection, which conflicts with the langgraph native stack on
> native Windows (libpq DLL clash — see `CLAUDE.md`). The chunk-count preview
> (`--dry-run`) is the exception; it touches neither Postgres nor Ollama.

### 1. Start Postgres with pgvector

```sh
docker compose up -d --wait
export DATABASE_URL=postgresql://auspex:auspex@localhost:5432/auspex
```

`docker-compose.yml` uses the `pgvector/pgvector:pg16` image — stock
`postgres:16` lacks the `vector` extension the schema needs.

### 2. Apply the schema migration

```sh
alembic upgrade head
```

Migration `0003` enables the `vector` extension and creates `corpus_chunks`
(with a `vector(768)` embedding column and an HNSW cosine index).

### 3. Pull the embedding model

```sh
ollama pull nomic-embed-text
```

The corpus embedding model is **frozen** (`nomic-embed-text`, 768-dim — see
`llm/embeddings.py`). It is a controlled variable for the retrieval experiment:
the same model must embed every chunk and every query, so it is pinned in code,
not read from the environment. Changing it means a new migration (different
dimension) and a full re-ingest.

### 4. Ingest the corpus

```sh
# Preview chunk counts only — no Postgres, no Ollama (safe on native Windows):
python -m scripts.ingest_corpus --dry-run

# Full ingest at a pinned commit:
python -m scripts.ingest_corpus --commit <sha>   # defaults to HEAD
```

The script reads the repo **at the pinned commit** (via `git`, not the working
tree), chunks each file language-aware, embeds, and upserts on a content hash —
so it is idempotent and safe to re-run. Pass an explicit `--commit` to be
deliberate about which SHA the corpus freezes; `HEAD` is the default but freezes
whatever you happen to be sitting on. Expect ~175 chunks for the current repo.

---

## Task runner (Makefile)

Common workflows have `make` shortcuts (run `make` alone to list them):

| Command | What it does |
|---|---|
| `make install` | Install base Python dependencies |
| `make serve` | Run the web UI on :7860 |
| `make mcp` | Run the MCP server over stdio |
| `make test` / `make lint` / `make fmt` | pytest · ruff check · ruff autofix |
| `make setup` | One-time corpus bringup: Postgres + migrate + pull model |
| `make corpus` | Ingest the corpus (`make corpus COMMIT=<sha>` to pin) |
| `make corpus-dry` | Chunk-count preview (no DB/Ollama) |
| `make evals` | Run the evaluation suite |

The corpus targets (`setup`, `db-up`, `migrate`, `corpus`) carry the same
WSL2/Linux caveat noted above.

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
