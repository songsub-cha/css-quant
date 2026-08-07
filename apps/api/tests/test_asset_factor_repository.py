"""Integration test for ``SqlAlchemyAssetFactorRepository`` (SoT A6.1/C3).

Spins up a real Postgres container via ``testcontainers`` and runs the
actual Alembic migration chain against it — same rationale as
``test_market_price_repository.py``. ``asset_factors.asset_id`` has a FK to
``assets.id``, so every test here seeds a real ``assets`` row first.

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
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer

from src.adapters.asset_factor_repository import SqlAlchemyAssetFactorRepository
from src.adapters.asset_repository import SqlAlchemyAssetRepository
from src.adapters.db import get_engine
from src.domain.asset import AssetType, Exchange, Market
from src.domain.asset_factor import AssetFactor, AssetFactorInfo

_API_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def postgres_url() -> Generator[str, None, None]:
    try:
        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:  # noqa: BLE001 - Docker absence surfaces as varied exception types
        pytest.skip(f"Docker unavailable — skipping asset factor repository test ({exc})")
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


async def _seed_asset(session: AsyncSession, *, ticker: str = "005930") -> UUID:
    asset = await SqlAlchemyAssetRepository(session).upsert_active(
        ticker=ticker,
        name="삼성전자",
        market=Market.KR,
        asset_type=AssetType.STOCK,
        exchange=Exchange.KOSPI,
    )
    return asset.id


def _factor(
    asset_id: UUID, factor_date: date, *, roe: Decimal | None = Decimal("0.1")
) -> AssetFactorInfo:
    return AssetFactorInfo(
        asset_id=asset_id,
        factor_date=factor_date,
        momentum_3m=Decimal("0.05"),
        momentum_6m=Decimal("0.10"),
        dist_52w_high=Decimal("-0.02"),
        ma20_deviation=Decimal("0.01"),
        roe=roe,
        op_margin=Decimal("0.15"),
        revenue_growth_yoy=Decimal("0.08"),
        debt_ratio=Decimal("0.4"),
        per=Decimal("12.5"),
        pbr=Decimal("1.8"),
        avg_trading_value_20d=Decimal("2000000000"),
        volume_cv=Decimal("0.3"),
        volatility_60d=Decimal("0.02"),
        mdd_60d=Decimal("-0.15"),
        gap_frequency_60d=Decimal("0.05"),
        market_cap=Decimal("400000000000"),
        is_managed=False,
        is_alert=False,
        financial_data_as_of=date(2026, 3, 31),
    )


def test_upsert_inserts_new_factor_row(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            asset_id = await _seed_asset(session)
            repo = SqlAlchemyAssetFactorRepository(session)
            factor_date = date(2026, 8, 7)

            row = await repo.upsert(factor=_factor(asset_id, factor_date))

            assert row.asset_id == asset_id
            assert row.factor_date == factor_date
            assert row.roe == Decimal("0.1")

            result = await session.execute(
                sa.select(AssetFactor).where(
                    AssetFactor.asset_id == asset_id, AssetFactor.factor_date == factor_date
                )
            )
            assert result.scalar_one().roe == Decimal("0.1")

    asyncio.run(_run())


def test_upsert_updates_existing_row_in_place(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            asset_id = await _seed_asset(session)
            repo = SqlAlchemyAssetFactorRepository(session)
            factor_date = date(2026, 8, 7)

            first = await repo.upsert(factor=_factor(asset_id, factor_date, roe=Decimal("0.1")))
            second = await repo.upsert(factor=_factor(asset_id, factor_date, roe=Decimal("0.2")))

            assert first.asset_id == second.asset_id
            assert first.factor_date == second.factor_date
            assert second.roe == Decimal("0.2")

            result = await session.execute(
                sa.select(AssetFactor).where(
                    AssetFactor.asset_id == asset_id, AssetFactor.factor_date == factor_date
                )
            )
            rows = result.scalars().all()
            assert len(rows) == 1
            assert rows[0].roe == Decimal("0.2")

    asyncio.run(_run())


def test_upsert_with_none_factor_fields_persists_null(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            asset_id = await _seed_asset(session)
            repo = SqlAlchemyAssetFactorRepository(session)

            row = await repo.upsert(factor=_factor(asset_id, date(2026, 8, 7), roe=None))

            assert row.roe is None

    asyncio.run(_run())


def test_upsert_with_nonexistent_asset_id_raises_integrity_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            repo = SqlAlchemyAssetFactorRepository(session)
            with pytest.raises(IntegrityError):
                await repo.upsert(factor=_factor(uuid4(), date(2026, 8, 7)))

    asyncio.run(_run())


def test_upsert_concurrent_insert_race_recovers_via_requery_and_update(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            asset_id = await _seed_asset(session)
        factor_date = date(2026, 8, 7)

        async def _upsert(roe: Decimal) -> AssetFactor:
            async with session_factory() as session:
                repo = SqlAlchemyAssetFactorRepository(session)
                return await repo.upsert(factor=_factor(asset_id, factor_date, roe=roe))

        results = await asyncio.gather(_upsert(Decimal("0.1")), _upsert(Decimal("0.2")))

        assert results[0].asset_id == asset_id
        assert results[1].asset_id == asset_id

        async with session_factory() as session:
            result = await session.execute(
                sa.select(AssetFactor).where(
                    AssetFactor.asset_id == asset_id, AssetFactor.factor_date == factor_date
                )
            )
            rows = result.scalars().all()
            assert len(rows) == 1

    asyncio.run(_run())
