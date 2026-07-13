# Auspex task runner.
#
# `make` (no target) prints the target list. Most targets are thin wrappers over
# the commands in docs/reference/setup.md — the Makefile is the shortcut, that
# doc is the explanation.
#
# The corpus/DB targets (setup, db-up, migrate, corpus) open a psycopg2
# connection, which conflicts with the langgraph native stack on native Windows
# (libpq DLL clash — see CLAUDE.md). Run those from WSL2/Linux. Everything else
# (install, serve, test, lint, corpus-dry) is fine on Windows too.
#
# Quick start on a fresh machine:
#   make install    # Python deps
#   make setup      # Postgres up, migrate, pull the embedding model (one-time)
#   make corpus     # ingest the corpus at HEAD (re-run when the pin advances)

# Local docker-compose Postgres; override for Cloud SQL etc.
DATABASE_URL ?= postgresql://auspex:auspex@localhost:5432/auspex
# Commit to freeze the corpus at. Pass an explicit SHA to be deliberate about
# the pin, e.g. `make corpus COMMIT=9b8b08f`.
COMMIT ?= HEAD
# Keep in sync with EMBEDDING_MODEL in llm/embeddings.py (the frozen model).
EMBED_MODEL := nomic-embed-text

export DATABASE_URL

.PHONY: help install install-evals serve mcp evals \
        setup db-up db-down migrate embed-model corpus corpus-dry \
        test lint fmt

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# --- Dependencies & app entrypoints -----------------------------------------

install: ## Install base Python dependencies
	pip install -r requirements.txt

install-evals: ## Install eval-suite dependencies (assay + Anthropic judge)
	pip install -r evals/requirements.txt

serve: ## Run the FastAPI web UI on http://localhost:7860
	uvicorn app:app --reload --port 7860

mcp: ## Run the MCP server over stdio (for Claude Desktop et al.)
	python -m auspex.mcp_server

evals: ## Run the evaluation suite
	python -m evals.run

# --- Corpus store (RAG retrieval) -------------------------------------------

setup: db-up migrate embed-model ## One-time environment bringup (DB + schema + model)

db-up: ## Start local Postgres+pgvector, wait until it accepts connections
	docker compose up -d --wait

db-down: ## Stop local Postgres (keeps the data volume)
	docker compose down

migrate: ## Apply DB migrations (idempotent; no-op if already at head)
	alembic upgrade head

embed-model: ## Pull the frozen embedding model (no-op if already present)
	ollama pull $(EMBED_MODEL)

corpus: migrate ## Ingest the corpus at COMMIT (default HEAD) — idempotent
	python -m scripts.ingest_corpus --commit $(COMMIT)

corpus-dry: ## Chunk-count preview only — no DB, no Ollama (works on Windows)
	python -m scripts.ingest_corpus --dry-run

# --- Quality ----------------------------------------------------------------

test: ## Run the test suite
	pytest

lint: ## Run ruff
	ruff check .

fmt: ## Auto-fix lint issues with ruff
	ruff check --fix .
