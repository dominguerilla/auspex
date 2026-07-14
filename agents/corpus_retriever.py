"""
CONCEPT: Corpus Retriever Agent — Vector Retrieval (RAG Phase 1)
================================================================
Pattern: Flag-gated node, parallel to the web searcher, feeding the reader.

This node is the single independent variable of the Phase 1 A/B experiment.
It runs on every graph invocation but is INERT unless ``state["retrieval"]``
is "on" — flipping that one flag is the only thing that changes between the
web-only baseline and the retrieval condition (see the build plan §1.0). Keeping
the node always present (rather than adding/removing it from the graph) is what
makes "one pipeline, one codepath" literally true.

When active it:
  1. embeds the research question with the frozen corpus model (llm/embeddings),
  2. runs a cosine top-k (k=8) query over corpus_chunks in pgvector,
  3. returns provenance-tagged RetrievedChunks (file_path, lines, commit_sha) so
     the writer can cite corpus evidence at file+line.

No reranking, no query rewriting — those are deferred until the baseline number
exists (§1.1). Positioned parallel to the searcher: both feed the reader.

State fields read:    retrieval, research_question
State fields written: corpus_results
"""

import logging
import os
import time

from graph.state import ResearchState, RetrievedChunk

logger = logging.getLogger(__name__)

# Number of chunks retrieved per query. Fixed at 8 for v1 (build plan §1.2);
# the token budget this implies is held identical across A/B conditions.
TOP_K = 8

# Which corpus generation to retrieve from. A new commit SHA is a new corpus
# generation; at Phase 1 scale there is a single generation, so filtering by
# name is sufficient. (Pinning to a specific commit_sha pairs with the drift
# study and is deferred.)
_CORPUS_NAME = os.environ.get("AUSPEX_CORPUS_NAME", "auspex-develop")
_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql://auspex:auspex@localhost:5432/auspex"
)


def _get_conn():
    """Open a psycopg2 connection with dict-style rows.

    psycopg2 (not psycopg3) for the same reason as the MCP job store: psycopg3's
    bundled libpq conflicts with the langgraph native stack in-process on Windows
    (see docs/adr/0004, CLAUDE.md). Imported lazily so the web-only path never
    needs psycopg2 installed/loaded.
    """
    import psycopg2
    import psycopg2.extras

    return psycopg2.connect(_DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)


def _retrieve(query: str) -> list[RetrievedChunk]:
    """Embed the query and return the cosine top-k corpus chunks."""
    from llm.embeddings import get_embedder, to_pgvector_literal

    query_vec = to_pgvector_literal(get_embedder().embed_query(query))

    # `<=>` is cosine distance (the HNSW index uses vector_cosine_ops), so lower
    # is closer; similarity = 1 - distance. The vector is bound once in the
    # SELECT expression and ORDER BY reuses the alias.
    sql = """
        SELECT id, file_path, start_line, end_line, commit_sha, content,
               embedding <=> %s::vector AS distance
        FROM corpus_chunks
        WHERE corpus_name = %s
        ORDER BY distance
        LIMIT %s
    """
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (query_vec, _CORPUS_NAME, TOP_K))
            rows = cur.fetchall()
    finally:
        conn.close()

    return [
        RetrievedChunk(
            chunk_id=row["id"],
            file_path=row["file_path"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            commit_sha=row["commit_sha"],
            content=row["content"],
            similarity=1.0 - float(row["distance"]),
            source="corpus",
        )
        for row in rows
    ]


def run_corpus_retriever(state: ResearchState) -> dict:
    """
    Retrieve corpus chunks for the research question when retrieval is enabled.

    Parameters
    ----------
    state : ResearchState
        Reads: retrieval, research_question

    Returns
    -------
    dict
        Keys: corpus_results (List[RetrievedChunk]) — empty when retrieval="off".
    """
    if state.get("retrieval", "off") != "on":
        return {"corpus_results": []}

    query = state["research_question"]
    started = time.perf_counter()
    chunks = _retrieve(query)
    latency_ms = (time.perf_counter() - started) * 1000

    # Per-query provenance/budget log (build plan §1.2): chunk ids, similarity
    # scores, context tokens added (~chars/4), and wall-clock retrieval latency.
    approx_tokens = sum(len(c["content"]) for c in chunks) // 4
    logger.info(
        "[corpus_retriever] k=%d ids=%s scores=%s ~tokens=%d latency=%.0fms",
        len(chunks),
        [c["chunk_id"] for c in chunks],
        [round(c["similarity"], 3) for c in chunks],
        approx_tokens,
        latency_ms,
    )

    return {"corpus_results": chunks}
