"""Frozen embedding model for the RAG corpus (Phase 1 + Phase 2).

The corpus embedding model is a *controlled variable* for the retrieval A/B
experiment: every chunk in ``corpus_chunks`` and every query embedded at
retrieval time must use the same model, or cosine scores aren't comparable and
the experiment is contaminated. So the model is pinned here as a constant, not
read from the environment the way the chat model is in ``llm/ollama_client.py``.

Chosen model: Ollama ``nomic-embed-text`` (768-dim). Local, free, reproducible
offline. The 768 dimension is baked into the ``corpus_chunks.embedding`` column
(alembic/0003); changing the model means changing that column and re-ingesting
the entire corpus. Freeze both together.

Pull the model once before ingesting or retrieving::

    ollama pull nomic-embed-text
"""

import os

# --- Frozen: do not change without a migration + full corpus re-ingest. ---
EMBEDDING_MODEL = "nomic-embed-text"
EMBEDDING_DIM = 768


def get_embedder():
    """Return the frozen corpus embedder (LangChain Embeddings interface).

    Reads ``OLLAMA_BASE_URL`` for the endpoint, mirroring ``get_llm()``: the
    native Ollama API is used (not the OpenAI-compatible ``/v1`` path), so a
    trailing ``/v1`` is stripped to allow either form in the env var.

    Returns
    -------
    OllamaEmbeddings
        Callers use ``.embed_documents(list[str])`` and ``.embed_query(str)``.
    """
    from langchain_ollama import OllamaEmbeddings

    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    base_url = base_url.rstrip("/").removesuffix("/v1")
    return OllamaEmbeddings(base_url=base_url, model=EMBEDDING_MODEL)


def describe_embedder() -> dict:
    """Provider/model/dim the corpus is embedded with, for run metadata."""
    return {
        "provider": "ollama",
        "model": EMBEDDING_MODEL,
        "dim": EMBEDDING_DIM,
    }


def to_pgvector_literal(vec) -> str:
    """Format an embedding as a pgvector text literal for a ``%s::vector`` bind.

    e.g. ``[0.1,0.2,...]``. Shared by the ingest INSERT and the retrieval query
    so both encode vectors identically.
    """
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"
