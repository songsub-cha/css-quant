"""Integration test for ``SqlAlchemyJobRunRepository`` (SoT C4).

Spins up a real Postgres container via ``testcontainers`` and runs the
actual Alembic migration chain against it before exercising the repository
— a plain ``Base.metadata.create_all()`` would not reproduce the
hand-written ``job_run_status`` Postgres enum type the way the real
migration does (``alembic/versions/ffbe282d9f4f_create_job_runs_table.py``),
so a create_all-backed test could pass even if the model's
``values_callable`` were missing or wrong. Same pattern as
``test_asset_repository.py``/``test_market_price_repository.py``.

Docker is unavailable in this environment and in the css-executor worktree
(``tests/conftest.py`` — "no DB container in this environment"), so the
module-scoped ``postgres_url`` fixture below skips the whole module when
Docker can't be reached. Only Docker-equipped CI actually exercises the
assertions here.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
from collections.abc import Generator
from datetime import date
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.exc import NoResultFound
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer

from src.adapters.db import get_engine
from src.adapters.job_run_repository import SqlAlchemyJobRunRepository
from src.domain.job_run import JobRunStatus

_API_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def postgres_url() -> Generator[str, None, None]:
    try:
        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:  # noqa: BLE001 - Docker absence surfaces as varied exception types
        pytest.skip(f"Docker unavailable — skipping job run repository test ({exc})")
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


def _run_alembic(database_url: str, *args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_API_ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
        check=True,
    )


@pytest.fixture(scope="module")
def migrated_database_url(postgres_url: str) -> str:
    _run_alembic(postgres_url, "upgrade", "head")
    return postgres_url


@pytest.fixture(scope="module")
def engine(migrated_database_url: str) -> Generator[AsyncEngine, None, None]:
    eng = get_engine(migrated_database_url)
    try:
        yield eng
    finally:
        asyncio.run(eng.dispose())


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def test_start_inserts_new_running_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            repo = SqlAlchemyJobRunRepository(session)
            run_date = date(2026, 7, 29)
            row = await repo.start(job_name="sync_assets", run_date=run_date)

            assert row.job_name == "sync_assets"
            assert row.run_date == run_date
            assert row.status == JobRunStatus.RUNNING
            assert row.finished_at is None

    asyncio.run(_run())


def test_finish_updates_status_and_terminal_fields(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            repo = SqlAlchemyJobRunRepository(session)
            started = await repo.start(job_name="sync_prices", run_date=date(2026, 7, 29))

            finished = await repo.finish(
                started.id,
                status=JobRunStatus.SUCCESS,
                stats={"synced": 42},
            )

            assert finished.id == started.id
            assert finished.status == JobRunStatus.SUCCESS
            assert finished.finished_at is not None
            assert finished.stats == {"synced": 42}
            assert finished.error is None

    asyncio.run(_run())


def test_finish_records_error_on_failure(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            repo = SqlAlchemyJobRunRepository(session)
            started = await repo.start(job_name="sync_prices", run_date=date(2026, 7, 30))

            finished = await repo.finish(
                started.id,
                status=JobRunStatus.FAILED,
                error="data source timed out",
            )

            assert finished.status == JobRunStatus.FAILED
            assert finished.error == "data source timed out"

    asyncio.run(_run())


def test_finish_with_nonexistent_job_run_id_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            repo = SqlAlchemyJobRunRepository(session)
            with pytest.raises(NoResultFound):
                await repo.finish(uuid4(), status=JobRunStatus.SUCCESS)

    asyncio.run(_run())
