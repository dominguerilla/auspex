"""Alembic environment for the MCP server's Postgres job store.

The database URL comes from the DATABASE_URL env var (libpq form, e.g.
``postgresql://user:pass@host:5432/db``). We adapt it to the SQLAlchemy +
psycopg3 driver form for the migration engine. Migrations are authored as raw
SQL (no ORM models), so ``target_metadata`` is None and autogenerate is unused.
"""

import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = None

_DEFAULT_URL = "postgresql://auspex:auspex@localhost:5432/auspex"


def _sqlalchemy_url() -> str:
    # SQLAlchemy's default postgresql dialect uses psycopg2, which the project
    # standardizes on (see docs/adr/0004). A plain postgresql:// URL selects it.
    url = os.environ.get("DATABASE_URL", _DEFAULT_URL)
    if url.startswith("postgresql+psycopg://"):
        url = url.replace("postgresql+psycopg://", "postgresql://", 1)
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_sqlalchemy_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _sqlalchemy_url()
    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
