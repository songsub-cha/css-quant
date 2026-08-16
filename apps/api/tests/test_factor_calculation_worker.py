"""Worker-level orchestration tests for ``calculate_factors`` (SoT A6.1 stage 2).

Exercises ``src.workers.factor_calculation.calculate_factors`` against
``tests/conftest.py``'s in-memory fakes -- no live DB, same shape as
``test_universe_filter_worker.py``.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from src.domain.asset import AssetType, Exchange, Market
from src.domain.financial_statement import ConsolidatedType, FinancialStatementInfo, FiscalQuarter
from src.domain.market_price import DailyPriceInfo
from src.domain.universe_filter import UniverseThresholds
from src.workers.factor_calculation import calculate_factors

from .conftest import (
    FakeAssetFactorRepository,
    FakeAssetRepository,
    FakeFinancialStatementRepository,
    FakeMarketPriceRepository,
)

_AS_OF = date(2026, 4, 1)
_THRESHOLDS = UniverseThresholds(
    market_cap_min=Decimal("300000000000"),
    avg_trading_value_min=Decimal("1000000000"),
    min_listed_days=60,
)


def _bar(
    ticker: str,
    trade_date: date,
    *,
    trading_value: int,
    market_cap: int | None,
    close: int = 100,
) -> DailyPriceInfo:
    return DailyPriceInfo(
        ticker=ticker,
        date=trade_date,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        adjusted_close=Decimal(close),
        volume=1_000_000,
        trading_value=Decimal(trading_value),
        market_cap=Decimal(market_cap) if market_cap is not None else None,
    )


async def _seed_trading_days(
    price_repo: FakeMarketPriceRepository,
    asset_id: UUID,
    ticker: str,
    *,
    end: date,
    days: int,
    trading_value: int,
    market_cap: int | None,
) -> None:
    d = end - timedelta(days=days - 1)
    while d <= end:
        await price_repo.upsert(
            asset_id=asset_id,
            bar=_bar(ticker, d, trading_value=trading_value, market_cap=market_cap),
        )
        d += timedelta(days=1)


def _fs(
    ticker: str,
    fiscal_year: int,
    fiscal_quarter: FiscalQuarter,
    *,
    net_income: Decimal,
    disclosed_at: date,
    rcept_no: str,
    total_equity: Decimal = Decimal(5000),
) -> FinancialStatementInfo:
    return FinancialStatementInfo(
        ticker=ticker,
        fiscal_year=fiscal_year,
        fiscal_quarter=fiscal_quarter,
        consolidated_type=ConsolidatedType.CFS,
        revenue=Decimal(1000),
        operating_income=Decimal(200),
        net_income=net_income,
        total_assets=total_equity + Decimal(2000),
        total_liabilities=Decimal(2000),
        total_equity=total_equity,
        disclosed_at=disclosed_at,
        rcept_no=rcept_no,
    )


def test_calculate_factors_only_writes_rows_for_universe_included_assets() -> None:
    async def _run() -> None:
        asset_repo = FakeAssetRepository()
        price_repo = FakeMarketPriceRepository()
        statement_repo = FakeFinancialStatementRepository()
        factor_repo = FakeAssetFactorRepository()

        qualifying = await asset_repo.upsert_active(
            ticker="005930",
            name="삼성전자",
            market=Market.KR,
            asset_type=AssetType.STOCK,
            exchange=Exchange.KOSPI,
        )
        small_cap = await asset_repo.upsert_active(
            ticker="000001",
            name="소형주",
            market=Market.KR,
            asset_type=AssetType.STOCK,
            exchange=Exchange.KOSPI,
        )

        await _seed_trading_days(
            price_repo,
            qualifying.id,
            "005930",
            end=_AS_OF,
            days=252,
            trading_value=2_000_000_000,
            market_cap=400_000_000_000,
        )
        await _seed_trading_days(
            price_repo,
            small_cap.id,
            "000001",
            end=_AS_OF,
            days=252,
            trading_value=2_000_000_000,
            market_cap=1_000_000_000,
        )

        results = await calculate_factors(
            asset_repo,
            price_repo,
            statement_repo,
            factor_repo,
            as_of_date=_AS_OF,
            thresholds=_THRESHOLDS,
        )

        assert {f.asset_id for f in results} == {qualifying.id}
        assert {f.asset_id for f in factor_repo.factors} == {qualifying.id}

    asyncio.run(_run())


def test_calculate_factors_ignores_future_disclosed_financial_statements() -> None:
    """A6.7.2 look-ahead regression guard: a statement disclosed after ``as_of_date``
    must never enter the TTM window, even when it is for a period chronologically
    after the last legitimately-disclosed quarter."""

    async def _run() -> None:
        asset_repo = FakeAssetRepository()
        price_repo = FakeMarketPriceRepository()
        statement_repo = FakeFinancialStatementRepository()
        factor_repo = FakeAssetFactorRepository()

        asset = await asset_repo.upsert_active(
            ticker="005930",
            name="삼성전자",
            market=Market.KR,
            asset_type=AssetType.STOCK,
            exchange=Exchange.KOSPI,
        )
        await _seed_trading_days(
            price_repo,
            asset.id,
            "005930",
            end=_AS_OF,
            days=252,
            trading_value=2_000_000_000,
            market_cap=400_000_000_000,
        )

        await statement_repo.upsert(
            asset_id=asset.id,
            statement=_fs(
                "005930",
                2025,
                FiscalQuarter.Q1,
                net_income=Decimal(40),
                disclosed_at=date(2025, 5, 15),
                rcept_no="R1",
            ),
        )
        await statement_repo.upsert(
            asset_id=asset.id,
            statement=_fs(
                "005930",
                2025,
                FiscalQuarter.H1,
                net_income=Decimal(90),
                disclosed_at=date(2025, 8, 14),
                rcept_no="R2",
            ),
        )
        await statement_repo.upsert(
            asset_id=asset.id,
            statement=_fs(
                "005930",
                2025,
                FiscalQuarter.Q3,
                net_income=Decimal(150),
                disclosed_at=date(2025, 11, 14),
                rcept_no="R3",
            ),
        )
        await statement_repo.upsert(
            asset_id=asset.id,
            statement=_fs(
                "005930",
                2025,
                FiscalQuarter.ANNUAL,
                net_income=Decimal(220),
                disclosed_at=date(2026, 3, 31),
                rcept_no="R4",
            ),
        )
        # Leaked/future-disclosed quarter -- must not affect this as_of_date run.
        await statement_repo.upsert(
            asset_id=asset.id,
            statement=_fs(
                "005930",
                2026,
                FiscalQuarter.Q1,
                net_income=Decimal(999_999),
                disclosed_at=date(2026, 5, 15),
                rcept_no="R5",
            ),
        )

        (result,) = await calculate_factors(
            asset_repo,
            price_repo,
            statement_repo,
            factor_repo,
            as_of_date=_AS_OF,
            thresholds=_THRESHOLDS,
        )

        # net_income_ttm = 40 + (90-40) + (150-90) + (220-150) = 220, the
        # full disclosed fiscal year -- the leaked 999_999 must not appear.
        assert result.roe == Decimal(220) / Decimal(5000)
        assert result.financial_data_as_of == date(2026, 3, 31)

    asyncio.run(_run())


def test_calculate_factors_fills_universe_snapshot_fields() -> None:
    async def _run() -> None:
        asset_repo = FakeAssetRepository()
        price_repo = FakeMarketPriceRepository()
        statement_repo = FakeFinancialStatementRepository()
        factor_repo = FakeAssetFactorRepository()

        asset = await asset_repo.upsert_active(
            ticker="005930",
            name="삼성전자",
            market=Market.KR,
            asset_type=AssetType.STOCK,
            exchange=Exchange.KOSPI,
        )
        await _seed_trading_days(
            price_repo,
            asset.id,
            "005930",
            end=_AS_OF,
            days=252,
            trading_value=2_000_000_000,
            market_cap=456_000_000_000,
        )

        (result,) = await calculate_factors(
            asset_repo,
            price_repo,
            statement_repo,
            factor_repo,
            as_of_date=_AS_OF,
            thresholds=_THRESHOLDS,
        )

        assert result.market_cap == Decimal(456_000_000_000)
        assert result.is_managed is False
        assert result.is_alert is False
        assert result.avg_trading_value_20d == Decimal(2_000_000_000)
        assert result.factor_date == _AS_OF

    asyncio.run(_run())


def test_calculate_factors_returns_empty_when_no_asset_included() -> None:
    async def _run() -> None:
        asset_repo = FakeAssetRepository()
        price_repo = FakeMarketPriceRepository()
        statement_repo = FakeFinancialStatementRepository()
        factor_repo = FakeAssetFactorRepository()

        results = await calculate_factors(
            asset_repo,
            price_repo,
            statement_repo,
            factor_repo,
            as_of_date=_AS_OF,
            thresholds=_THRESHOLDS,
        )

        assert results == []
        assert factor_repo.factors == []

    asyncio.run(_run())
