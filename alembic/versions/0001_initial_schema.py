"""initial schema: jobs + sources

Mirrors the SQLite job store the MCP server used (jobs), adds the durable
``sources`` table (cross-run scrape cache + provenance) and the ``agent_model``
column (eval attribution) per docs/proposals/0002 and docs/adr/0004.

Authored as raw SQL (no ORM) per the raw-SQL migration decision.

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-06-16

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE jobs (
            id             TEXT        PRIMARY KEY,
            question       TEXT        NOT NULL,
            status         TEXT        NOT NULL,
            report         TEXT,
            error          TEXT,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            completed_at   TIMESTAMPTZ,
            max_iterations INTEGER,
            duration_ms    INTEGER,
            agent_model    TEXT
        )
        """
    )
    op.execute(
        """
        CREATE TABLE sources (
            id          BIGSERIAL   PRIMARY KEY,
            job_id      TEXT        NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
            url         TEXT        NOT NULL,
            summary     TEXT        NOT NULL,
            raw_length  INTEGER     NOT NULL,
            scraped_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX idx_sources_url ON sources (url)")
    op.execute("CREATE INDEX idx_sources_job ON sources (job_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS sources")
    op.execute("DROP TABLE IF EXISTS jobs")
