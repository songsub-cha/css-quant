"""Integration test for ``SqlAlchemyIndexPriceRepository`` (SoT A6.2/A6.3).

Spins up a real Postgres container via ``testcontainers`` and runs the
actual Alembic migration chain against it before exercising the repository
— same rationale as ``test_market_price_repository.py``.

Unlike ``market_prices``, ``index_prices`` has no FK to seed around: there
is no ``assets`` row prerequisite, so the "insert against a nonexistent
parent raises IntegrityError" case from ``test_market_price_repository.py``
doesn't apply here. Instead, the TOCTOU recovery path
(``SqlAlchemyIndexPriceRepository.upsert``'s except-``IntegrityError``
branch) is exercised with a genuine concurrent insert race via
``asyncio.gather`` — two coroutines racing to upsert the same
``(index_code, date)`` key, relying on real Postgres to reject the loser's
insert.

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
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer

from src.adapters.db import get_engine
from src.adapters.index_price_repository import SqlAlchemyIndexPriceRepository
from src.domain.index_price import IndexCode, IndexPrice, IndexPriceInfo

_API_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def postgres_url() -> Generator[str, None, None]:
    try:
        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:  # noqa: BLE001 - Docker absence surfaces as varied exception types
        pytest.skip(f"Docker unavailable — skipping index price repository test ({exc})")
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


def _bar(trade_date: date, close: int = 2_665) -> IndexPriceInfo:
    return IndexPriceInfo(
        index_code=IndexCode.KOSPI,
        date=trade_date,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=450_000_000,
        trading_value=Decimal(close * 450_000_000),
    )


def test_upsert_inserts_new_bar(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            repo = SqlAlchemyIndexPriceRepository(session)
            trade_date = date(2026, 7, 29)
            row = await repo.upsert(bar=_bar(trade_date))

            assert row.index_code == IndexCode.KOSPI
            assert row.date == trade_date
            assert row.close == Decimal(2_665)

            result = await session.execute(
                sa.select(IndexPrice).where(
                    IndexPrice.index_code == IndexCode.KOSPI, IndexPrice.date == trade_date
                )
            )
            assert result.scalar_one().close == Decimal(2_665)

    asyncio.run(_run())


def test_upsert_updates_existing_bar_in_place(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            repo = SqlAlchemyIndexPriceRepository(session)
            trade_date = date(2026, 7, 30)
            first = await repo.upsert(bar=_bar(trade_date, close=2_665))
            second = await repo.upsert(bar=_bar(trade_date, close=2_700))

            assert first.index_code == second.index_code
            assert first.date == second.date
            assert second.close == Decimal(2_700)

            result = await session.execute(
                sa.select(IndexPrice).where(
                    IndexPrice.index_code == IndexCode.KOSPI, IndexPrice.date == trade_date
                )
            )
            rows = result.scalars().all()
            assert len(rows) == 1
            assert rows[0].close == Decimal(2_700)

    asyncio.run(_run())


def test_upsert_concurrent_insert_race_recovers_via_requery_and_update(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        trade_date = date(2026, 7, 31)

        async def _upsert(close: int) -> IndexPrice:
            async with session_factory() as session:
                repo = SqlAlchemyIndexPriceRepository(session)
                return await repo.upsert(bar=_bar(trade_date, close=close))

        results = await asyncio.gather(_upsert(2_665), _upsert(2_700))

        assert results[0].index_code == IndexCode.KOSPI
        assert results[1].index_code == IndexCode.KOSPI
        assert results[0].date == trade_date
        assert results[1].date == trade_date

        async with session_factory() as session:
            result = await session.execute(
                sa.select(IndexPrice).where(
                    IndexPrice.index_code == IndexCode.KOSPI, IndexPrice.date == trade_date
                )
            )
            rows = result.scalars().all()
            assert len(rows) == 1

    asyncio.run(_run())
