"""Alembic environment.

Outside the layered package graph (SoT B2 only orders
domain/adapters/services/api-v1/engine/workers), so — like ``api/deps.py`` —
this module is allowed to import ``src.config`` directly (SoT B5.5: Alembic
runs against the app's async engine, built from ``settings.DATABASE_URL``).
Engine construction is delegated to ``src.adapters.db.get_engine`` so there
is exactly one place that calls ``create_async_engine`` for this app.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy.engine import Connection
from sqlalchemy.pool import NullPool

from alembic import context
from src.adapters.db import get_engine
from src.config import Settings
from src.domain.base import Base

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Domain models registered against Base.metadata power `alembic revision
# --autogenerate`. No ORM models exist yet in this issue's scope.
target_metadata = Base.metadata

DATABASE_URL = Settings().database_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    context.configure(
        url=DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    NullPool: Alembic opens one connection, runs migrations, and exits —
    a pooled engine would just leave idle connections behind.
    """
    connectable = get_engine(DATABASE_URL, poolclass=NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
