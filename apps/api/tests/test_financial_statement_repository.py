"""Integration test for ``SqlAlchemyFinancialStatementRepository`` (SoT C1/A6.1).

Spins up a real Postgres container via ``testcontainers`` and runs the
actual Alembic migration chain against it — same rationale as
``test_index_price_repository.py``. Unlike ``index_prices``, there is an
``assets`` FK prerequisite, so an asset row is seeded first (same pattern as
``test_market_price_repository.py``).

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
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from testcontainers.community.postgres import PostgresContainer

from src.adapters.db import get_engine
from src.adapters.financial_statement_repository import SqlAlchemyFinancialStatementRepository
from src.domain.financial_statement import (
    ConsolidatedType,
    FinancialStatement,
    FinancialStatementInfo,
    FiscalQuarter,
)
from src.domain.ids import generate_uuid7

_API_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def postgres_url() -> Generator[str, None, None]:
    try:
        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:  # noqa: BLE001 - Docker absence surfaces as varied exception types
        pytest.skip(f"Docker unavailable — skipping financial statement repository test ({exc})")
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


async def _seed_asset(session: AsyncSession, *, ticker: str) -> UUID:
    asset_id = generate_uuid7()
    await session.execute(
        sa.text(
            """
            INSERT INTO assets (id, ticker, name, market, asset_type, exchange, is_active)
            VALUES (:id, :ticker, 'Test Asset', 'KR', 'STOCK', 'KOSPI', true)
            """
        ),
        {"id": asset_id, "ticker": ticker},
    )
    await session.commit()
    return asset_id


def _statement(rcept_no: str, close: int = 1_000) -> FinancialStatementInfo:
    return FinancialStatementInfo(
        ticker="005930",
        fiscal_year=2025,
        fiscal_quarter=FiscalQuarter.ANNUAL,
        consolidated_type=ConsolidatedType.CFS,
        revenue=Decimal(close),
        operating_income=Decimal(close),
        net_income=Decimal(close),
        total_assets=Decimal(close),
        total_liabilities=Decimal(close),
        total_equity=Decimal(close),
        disclosed_at=date(2026, 3, 31),
        rcept_no=rcept_no,
    )


def test_upsert_inserts_new_statement(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            asset_id = await _seed_asset(session, ticker="005930")
            repo = SqlAlchemyFinancialStatementRepository(session)

            row = await repo.upsert(asset_id=asset_id, statement=_statement("20260331000001"))

            assert row.asset_id == asset_id
            assert row.fiscal_year == 2025
            assert row.fiscal_quarter == FiscalQuarter.ANNUAL
            assert row.revenue == Decimal(1_000)

            result = await session.execute(
                sa.select(FinancialStatement).where(FinancialStatement.asset_id == asset_id)
            )
            assert result.scalar_one().rcept_no == "20260331000001"

    asyncio.run(_run())


def test_upsert_restatement_updates_rcept_no_and_line_items_in_place(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            asset_id = await _seed_asset(session, ticker="000660")
            repo = SqlAlchemyFinancialStatementRepository(session)
            first = await repo.upsert(
                asset_id=asset_id, statement=_statement("20260331000002", close=1_000)
            )

            second = await repo.upsert(
                asset_id=asset_id, statement=_statement("20260415000003", close=1_200)
            )

            assert second.asset_id == first.asset_id
            assert second.fiscal_year == first.fiscal_year
            assert second.fiscal_quarter == first.fiscal_quarter
            assert second.rcept_no == "20260415000003"
            assert second.revenue == Decimal(1_200)

            result = await session.execute(
                sa.select(FinancialStatement).where(FinancialStatement.asset_id == asset_id)
            )
            rows = result.scalars().all()
            assert len(rows) == 1
            assert rows[0].rcept_no == "20260415000003"

    asyncio.run(_run())


def test_upsert_concurrent_insert_race_recovers_via_requery_and_update(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            asset_id = await _seed_asset(session, ticker="086520")

        async def _upsert(rcept_no: str) -> FinancialStatement:
            async with session_factory() as session:
                repo = SqlAlchemyFinancialStatementRepository(session)
                return await repo.upsert(asset_id=asset_id, statement=_statement(rcept_no))

        results = await asyncio.gather(
            _upsert("20260331000004"), _upsert("20260331000005")
        )

        assert results[0].asset_id == asset_id
        assert results[1].asset_id == asset_id

        async with session_factory() as session:
            result = await session.execute(
                sa.select(FinancialStatement).where(FinancialStatement.asset_id == asset_id)
            )
            rows = result.scalars().all()
            assert len(rows) == 1

    asyncio.run(_run())
