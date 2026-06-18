"""job progress columns: current_node + iteration

Adds live-progress columns to ``jobs`` so get_research_status reflects the
active pipeline node and iteration even after the worker split (docs/adr/0005),
where status reads come from Postgres rather than the worker's memory.

Authored as raw SQL (no ORM) per the raw-SQL migration decision.

Revision ID: 0002_job_progress
Revises: 0001_initial_schema
Create Date: 2026-06-17

"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002_job_progress"
down_revision: Union[str, None] = "0001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE jobs ADD COLUMN current_node TEXT")
    op.execute("ALTER TABLE jobs ADD COLUMN iteration INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE jobs DROP COLUMN iteration")
    op.execute("ALTER TABLE jobs DROP COLUMN current_node")
