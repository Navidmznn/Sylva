"""
alembic env.py — pulls the URL from $DATABASE_URL (driver swapped to psycopg
for the sync engine alembic uses) and the metadata from db_models.Base.
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from db_models import Base


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Override the alembic.ini URL with the live env var, mapping the asyncpg
# driver string to the sync psycopg driver alembic expects.
env_url = os.environ.get("DATABASE_URL")
if env_url:
    config.set_main_option("sqlalchemy.url", env_url.replace("+asyncpg", "+psycopg", 1))

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
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
