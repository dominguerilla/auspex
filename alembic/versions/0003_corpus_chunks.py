"""corpus_chunks: pgvector store for flat retrieval (RAG Phase 1)

Adds the pgvector extension and the ``corpus_chunks`` table that
``scripts/ingest_corpus.py`` populates. This is the flat-retrieval store for
the RAG A/B experiment (Phase 1). ``start_line``/``end_line``/``symbol_name``
are populated now even though flat retrieval ignores them — Phase 2's graph
nodes point at chunks through those columns.

The embedding column is ``vector(768)`` to match the frozen embedding model,
Ollama ``nomic-embed-text`` (see llm/embeddings.py). Changing the model means
changing this dimension and re-ingesting the whole corpus, so both are frozen
together.

Requires a Postgres image with pgvector (docker-compose uses
``pgvector/pgvector:pg16``; Cloud SQL has the extension available).

Authored as raw SQL (no ORM) per the raw-SQL migration decision.

Revision ID: 0003_corpus_chunks
Revises: 0002_job_progress
Create Date: 2026-07-07

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0003_corpus_chunks"
down_revision: Union[str, None] = "0002_job_progress"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE corpus_chunks (
            id            BIGSERIAL   PRIMARY KEY,
            corpus_name   TEXT        NOT NULL,   -- 'auspex-develop'
            commit_sha    TEXT        NOT NULL,
            file_path     TEXT        NOT NULL,
            chunk_index   INT         NOT NULL,
            start_line    INT,
            end_line      INT,
            content       TEXT        NOT NULL,
            content_hash  TEXT        NOT NULL,
            language      TEXT,                   -- 'python' | 'markdown' | 'terraform' | ...
            symbol_name   TEXT,                   -- function/class name when chunk = one symbol
            embedding     vector(768),            -- Ollama nomic-embed-text dim (see llm/embeddings.py)
            created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (corpus_name, content_hash)
        )
        """
    )
    # Approximate-nearest-neighbour index for cosine similarity (top-k retrieval).
    op.execute(
        "CREATE INDEX idx_corpus_chunks_embedding ON corpus_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS corpus_chunks")
    # Leave the vector extension in place: dropping it would break any other
    # object that depends on it, and it is harmless if unused.
