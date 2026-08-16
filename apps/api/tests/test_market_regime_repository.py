"""Integration test for ``SqlAlchemyMarketRegimeRepository`` (SoT A6.2/A6.3).

Spins up a real Postgres container via ``testcontainers`` and runs the
actual Alembic migration chain against it before exercising the repository
— same rationale as ``test_index_price_repository.py``.

Unlike ``index_prices``, ``market_regimes`` has no FK to seed around either;
the TOCTOU recovery path (``SqlAlchemyMarketRegimeRepository.upsert``'s
except-``IntegrityError`` branch) is exercised the same way, via a genuine
concurrent insert race on the same ``regime_date``.

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
from src.adapters.market_regime_repository import SqlAlchemyMarketRegimeRepository
from src.domain.market_regime import MarketRegime, MarketRegimeInfo, RegimeStatus

_API_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def postgres_url() -> Generator[str, None, None]:
    try:
        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:  # noqa: BLE001 - Docker absence surfaces as varied exception types
        pytest.skip(f"Docker unavailable — skipping market regime repository test ({exc})")
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


def _regime(regime_date: date, regime: RegimeStatus = RegimeStatus.NORMAL) -> MarketRegimeInfo:
    return MarketRegimeInfo(
        regime_date=regime_date,
        regime=regime,
        kospi_close=Decimal("2665.1234"),
        kospi_ma200=Decimal("2600.5678"),
        vkospi=Decimal("18.5"),
        kospi_volatility_20d=Decimal("0.012345"),
        market_shock=False,
        signals={"raw_normal": regime == RegimeStatus.NORMAL},
    )


def test_upsert_inserts_new_row(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            repo = SqlAlchemyMarketRegimeRepository(session)
            regime_date = date(2026, 7, 29)
            row = await repo.upsert(regime=_regime(regime_date))

            assert row.regime_date == regime_date
            assert row.regime == RegimeStatus.NORMAL
            assert row.signals == {"raw_normal": True}

            result = await session.execute(
                sa.select(MarketRegime).where(MarketRegime.regime_date == regime_date)
            )
            assert result.scalar_one().kospi_close == Decimal("2665.1234")

    asyncio.run(_run())


def test_upsert_updates_existing_row_in_place(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            repo = SqlAlchemyMarketRegimeRepository(session)
            regime_date = date(2026, 7, 30)
            first = await repo.upsert(regime=_regime(regime_date, RegimeStatus.DEFENSIVE))
            second = await repo.upsert(regime=_regime(regime_date, RegimeStatus.NORMAL))

            assert first.regime_date == second.regime_date
            assert second.regime == RegimeStatus.NORMAL

            result = await session.execute(
                sa.select(MarketRegime).where(MarketRegime.regime_date == regime_date)
            )
            rows = result.scalars().all()
            assert len(rows) == 1
            assert rows[0].regime == RegimeStatus.NORMAL

    asyncio.run(_run())


def test_upsert_concurrent_insert_race_recovers_via_requery_and_update(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        regime_date = date(2026, 7, 31)

        async def _upsert(regime: RegimeStatus) -> MarketRegime:
            async with session_factory() as session:
                repo = SqlAlchemyMarketRegimeRepository(session)
                return await repo.upsert(regime=_regime(regime_date, regime))

        results = await asyncio.gather(
            _upsert(RegimeStatus.NORMAL), _upsert(RegimeStatus.DEFENSIVE)
        )

        assert results[0].regime_date == regime_date
        assert results[1].regime_date == regime_date

        async with session_factory() as session:
            result = await session.execute(
                sa.select(MarketRegime).where(MarketRegime.regime_date == regime_date)
            )
            rows = result.scalars().all()
            assert len(rows) == 1

    asyncio.run(_run())


def test_get_recent_returns_rows_strictly_before_end_date_most_recent_first(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            repo = SqlAlchemyMarketRegimeRepository(session)
            dates = [date(2026, 8, d) for d in (1, 2, 3, 4)]
            for d in dates:
                await repo.upsert(regime=_regime(d))

            recent = await repo.get_recent(before_date=date(2026, 8, 4), limit=2)

            assert [r.regime_date for r in recent] == [date(2026, 8, 3), date(2026, 8, 2)]

            # before_date itself must never be included, even though its row exists
            # (a same-day re-run of detect_market_regime must never see its own row
            # as "yesterday" — required for idempotent re-runs to reproduce the same
            # hysteresis input).
            recent_excludes_self = await repo.get_recent(before_date=date(2026, 8, 3), limit=10)
            assert date(2026, 8, 3) not in [r.regime_date for r in recent_excludes_self]

    asyncio.run(_run())


def test_get_by_date_returns_the_exact_day_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            repo = SqlAlchemyMarketRegimeRepository(session)
            await repo.upsert(regime=_regime(date(2026, 8, 5), RegimeStatus.DEFENSIVE))

            found = await repo.get_by_date(regime_date=date(2026, 8, 5))
            missing = await repo.get_by_date(regime_date=date(2026, 8, 6))

            assert found is not None
            assert found.regime_date == date(2026, 8, 5)
            assert found.regime == RegimeStatus.DEFENSIVE
            assert missing is None

    asyncio.run(_run())
