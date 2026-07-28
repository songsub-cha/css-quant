"""Integration test for ``SqlAlchemyMarketPriceRepository`` (SoT C1/C3).

Spins up a real Postgres container via ``testcontainers`` and runs the
actual Alembic migration chain against it before exercising the repository
— same rationale as ``test_asset_repository.py``: a plain
``Base.metadata.create_all()`` would not create the hand-written
``market_prices`` FK/PK the way the real migration does, so a
create_all-backed test could pass even if the upsert logic silently
violated them.

``market_prices.asset_id`` has a FK to ``assets.id``, so every test here
seeds a real ``assets`` row via ``SqlAlchemyAssetRepository`` first — unlike
``test_asset_repository.py``, an insert with no matching asset would fail
the FK rather than exercise the repository under test.

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
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer

from src.adapters.asset_repository import SqlAlchemyAssetRepository
from src.adapters.db import get_engine
from src.adapters.market_price_repository import SqlAlchemyMarketPriceRepository
from src.domain.asset import AssetType, Exchange, Market
from src.domain.market_price import DailyPriceInfo, MarketPrice

_API_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def postgres_url() -> Generator[str, None, None]:
    try:
        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:  # noqa: BLE001 - Docker absence surfaces as varied exception types
        pytest.skip(f"Docker unavailable — skipping market price repository test ({exc})")
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


def _bar(trade_date: date, close: int = 71_200) -> DailyPriceInfo:
    return DailyPriceInfo(
        ticker="005930",
        date=trade_date,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        adjusted_close=Decimal(close),
        volume=15_000_000,
        trading_value=Decimal(close * 15_000_000),
    )


def test_upsert_inserts_new_bar(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            asset = await SqlAlchemyAssetRepository(session).upsert_active(
                ticker="005930",
                name="삼성전자",
                market=Market.KR,
                asset_type=AssetType.STOCK,
                exchange=Exchange.KOSPI,
            )

            repo = SqlAlchemyMarketPriceRepository(session)
            trade_date = date(2026, 7, 29)
            row = await repo.upsert(asset_id=asset.id, bar=_bar(trade_date))

            assert row.asset_id == asset.id
            assert row.date == trade_date
            assert row.close == Decimal(71_200)

            result = await session.execute(
                sa.select(MarketPrice).where(
                    MarketPrice.asset_id == asset.id, MarketPrice.date == trade_date
                )
            )
            assert result.scalar_one().close == Decimal(71_200)

    asyncio.run(_run())


def test_upsert_updates_existing_bar_in_place(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            asset = await SqlAlchemyAssetRepository(session).upsert_active(
                ticker="000660",
                name="SK하이닉스",
                market=Market.KR,
                asset_type=AssetType.STOCK,
                exchange=Exchange.KOSPI,
            )

            repo = SqlAlchemyMarketPriceRepository(session)
            trade_date = date(2026, 7, 29)
            first = await repo.upsert(asset_id=asset.id, bar=_bar(trade_date, close=71_200))
            second = await repo.upsert(asset_id=asset.id, bar=_bar(trade_date, close=72_000))

            assert first.asset_id == second.asset_id
            assert first.date == second.date
            assert second.close == Decimal(72_000)

            result = await session.execute(
                sa.select(MarketPrice).where(
                    MarketPrice.asset_id == asset.id, MarketPrice.date == trade_date
                )
            )
            rows = result.scalars().all()
            assert len(rows) == 1
            assert rows[0].close == Decimal(72_000)

    asyncio.run(_run())


def test_upsert_with_nonexistent_asset_id_raises_integrity_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            repo = SqlAlchemyMarketPriceRepository(session)
            with pytest.raises(IntegrityError):
                await repo.upsert(asset_id=uuid4(), bar=_bar(date(2026, 7, 29)))

    asyncio.run(_run())
