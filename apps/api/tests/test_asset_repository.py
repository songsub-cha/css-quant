"""Integration test for ``SqlAlchemyAssetRepository`` (SoT C1/C3).

Spins up a real Postgres container via ``testcontainers`` and runs the
actual Alembic migration chain against it before exercising the repository
— a plain ``Base.metadata.create_all()`` would not create the
``(ticker, market) WHERE is_active`` partial unique index that
``upsert_active`` depends on (it's hand-written SQL in the migration, not
SQLAlchemy model metadata; see ``alembic/versions/5e8dcb0561bf_...py``), so
a create_all-backed test would pass even if the upsert logic silently
violated that index. Same pattern as ``test_asset_migration.py``.

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
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer

from src.adapters.asset_repository import SqlAlchemyAssetRepository
from src.adapters.db import get_engine
from src.domain.asset import Asset, AssetType, Exchange, Market

_API_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def postgres_url() -> Generator[str, None, None]:
    try:
        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:  # noqa: BLE001 - Docker absence surfaces as varied exception types
        pytest.skip(f"Docker unavailable — skipping asset repository integration test ({exc})")
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


def _select_by_ticker(ticker: str) -> sa.Select[tuple[Asset]]:
    return sa.select(Asset).where(Asset.ticker == ticker)


def test_upsert_active_inserts_new_ticker(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            repo = SqlAlchemyAssetRepository(session)
            asset = await repo.upsert_active(
                ticker="005930",
                name="삼성전자",
                market=Market.KR,
                asset_type=AssetType.STOCK,
                exchange=Exchange.KOSPI,
            )
            assert asset.ticker == "005930"
            assert asset.is_active is True

            fetched = await repo.get_active_by_ticker("005930", Market.KR)
            assert fetched is not None
            assert fetched.id == asset.id

    asyncio.run(_run())


def test_upsert_active_updates_existing_active_row_in_place(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            repo = SqlAlchemyAssetRepository(session)
            first = await repo.upsert_active(
                ticker="000660",
                name="Old Name",
                market=Market.KR,
                asset_type=AssetType.STOCK,
                exchange=Exchange.KOSPI,
            )
            second = await repo.upsert_active(
                ticker="000660",
                name="New Name",
                market=Market.KR,
                asset_type=AssetType.STOCK,
                exchange=Exchange.KOSDAQ,
            )

            assert second.id == first.id
            assert second.name == "New Name"
            assert second.exchange == Exchange.KOSDAQ

            result = await session.execute(_select_by_ticker("000660"))
            rows = result.scalars().all()
            assert len(rows) == 1

    asyncio.run(_run())


def test_upsert_active_relisting_creates_new_row_and_preserves_inactive_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            repo = SqlAlchemyAssetRepository(session)
            first = await repo.upsert_active(
                ticker="086520",
                name="에코프로",
                market=Market.KR,
                asset_type=AssetType.STOCK,
                exchange=Exchange.KOSDAQ,
            )

        # sync_assets never deactivates rows (out of scope — see
        # src/services/asset_sync.py); simulate delisting directly, the
        # same way test_asset_migration.py's relisting test does.
        async with session_factory() as session:
            await session.execute(
                sa.update(Asset).where(Asset.id == first.id).values(is_active=False)
            )
            await session.commit()

        async with session_factory() as session:
            repo = SqlAlchemyAssetRepository(session)
            relisted = await repo.upsert_active(
                ticker="086520",
                name="에코프로",
                market=Market.KR,
                asset_type=AssetType.STOCK,
                exchange=Exchange.KOSDAQ,
            )

            assert relisted.id != first.id

            result = await session.execute(_select_by_ticker("086520"))
            rows = result.scalars().all()
            assert len(rows) == 2
            assert sum(1 for r in rows if r.is_active) == 1
            assert sum(1 for r in rows if not r.is_active) == 1

    asyncio.run(_run())
