"""Integration test for ``SqlAlchemyAssetScoreRepository`` (SoT A6.1/C3).

Spins up a real Postgres container via ``testcontainers`` and runs the
actual Alembic migration chain against it — same rationale as
``test_asset_factor_repository.py``. ``ai_scores.asset_id`` has a FK to
``assets.id`` and ``ai_scores.regime`` uses the existing ``regime_status``
Postgres enum, so every test here seeds a real ``assets`` row first and
exercises the enum end-to-end.

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

from src.adapters.ai_score_repository import SqlAlchemyAssetScoreRepository
from src.adapters.asset_repository import SqlAlchemyAssetRepository
from src.adapters.db import get_engine
from src.domain.ai_score import AssetScore, AssetScoreInfo
from src.domain.asset import AssetType, Exchange, Market
from src.domain.market_regime import RegimeStatus

_API_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def postgres_url() -> Generator[str, None, None]:
    try:
        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:  # noqa: BLE001 - Docker absence surfaces as varied exception types
        pytest.skip(f"Docker unavailable — skipping ai score repository test ({exc})")
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


def _score(
    asset_id: UUID,
    score_date: date,
    *,
    regime: RegimeStatus = RegimeStatus.NORMAL,
    total_score: Decimal = Decimal("65.50"),
) -> AssetScoreInfo:
    return AssetScoreInfo(
        asset_id=asset_id,
        score_date=score_date,
        regime=regime,
        total_score=total_score,
        momentum_score=Decimal("70.00"),
        quality_score=Decimal("60.00"),
        value_score=Decimal("55.00"),
        liquidity_score=Decimal("80.00"),
        risk_score=Decimal("50.00"),
    )


def test_upsert_inserts_new_score_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            asset_id = await _seed_asset(session)
            repo = SqlAlchemyAssetScoreRepository(session)
            score_date = date(2026, 8, 16)

            row = await repo.upsert(score=_score(asset_id, score_date))

            assert row.asset_id == asset_id
            assert row.score_date == score_date
            assert row.regime == RegimeStatus.NORMAL
            assert row.total_score == Decimal("65.50")
            assert row.summary is None
            assert row.llm_model is None

            result = await session.execute(
                sa.select(AssetScore).where(
                    AssetScore.asset_id == asset_id, AssetScore.score_date == score_date
                )
            )
            assert result.scalar_one().total_score == Decimal("65.50")

    asyncio.run(_run())


def test_upsert_updates_existing_row_in_place(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            asset_id = await _seed_asset(session)
            repo = SqlAlchemyAssetScoreRepository(session)
            score_date = date(2026, 8, 16)

            first = await repo.upsert(
                score=_score(asset_id, score_date, total_score=Decimal("50.00"))
            )
            second = await repo.upsert(
                score=_score(
                    asset_id,
                    score_date,
                    regime=RegimeStatus.DEFENSIVE,
                    total_score=Decimal("40.00"),
                )
            )

            assert first.asset_id == second.asset_id
            assert second.total_score == Decimal("40.00")
            assert second.regime == RegimeStatus.DEFENSIVE

            result = await session.execute(
                sa.select(AssetScore).where(
                    AssetScore.asset_id == asset_id, AssetScore.score_date == score_date
                )
            )
            rows = result.scalars().all()
            assert len(rows) == 1
            assert rows[0].total_score == Decimal("40.00")

    asyncio.run(_run())


def test_upsert_with_nonexistent_asset_id_raises_integrity_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            repo = SqlAlchemyAssetScoreRepository(session)
            with pytest.raises(IntegrityError):
                await repo.upsert(score=_score(uuid4(), date(2026, 8, 16)))

    asyncio.run(_run())


def test_upsert_concurrent_insert_race_recovers_via_requery_and_update(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with session_factory() as session:
            asset_id = await _seed_asset(session)
        score_date = date(2026, 8, 16)

        async def _upsert(total_score: Decimal) -> AssetScore:
            async with session_factory() as session:
                repo = SqlAlchemyAssetScoreRepository(session)
                return await repo.upsert(
                    score=_score(asset_id, score_date, total_score=total_score)
                )

        results = await asyncio.gather(
            _upsert(Decimal("50.00")), _upsert(Decimal("60.00"))
        )

        assert results[0].asset_id == asset_id
        assert results[1].asset_id == asset_id

        async with session_factory() as session:
            result = await session.execute(
                sa.select(AssetScore).where(
                    AssetScore.asset_id == asset_id, AssetScore.score_date == score_date
                )
            )
            rows = result.scalars().all()
            assert len(rows) == 1

    asyncio.run(_run())
