"""``backfill_market_data``/``backfill_financial_statements`` (SoT C2/A6.7.6, services layer).

No DB container in this environment: exercised against the same
``conftest`` fakes ``test_price_sync.py``/``test_index_price_sync_service.py``/
``test_financial_statement_sync.py`` use. Uses ``asyncio.run`` directly (no
pytest-asyncio dependency in this project).
"""

from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

import pytest

from src.adapters.dart_financial_data_source import DartSystemicError
from src.domain.asset import AssetType, Exchange, Market
from src.domain.financial_statement import ConsolidatedType, FinancialStatementInfo, FiscalQuarter
from src.domain.index_price import IndexCode, IndexPriceInfo
from src.domain.market_price import DailyPriceInfo
from src.services.backfill import backfill_financial_statements, backfill_market_data

from .conftest import (
    FakeAssetRepository,
    FakeFinancialStatementRepository,
    FakeIndexPriceRepository,
    FakeMarketPriceRepository,
)


class _StubPriceDataSource:
    def __init__(
        self,
        bars_by_date: dict[date, list[DailyPriceInfo]],
        failing_dates: frozenset[date] = frozenset(),
    ) -> None:
        self._bars_by_date = bars_by_date
        self._failing_dates = failing_dates

    async def get_daily_ohlcv(self, trade_date: date) -> list[DailyPriceInfo]:
        if trade_date in self._failing_dates:
            raise RuntimeError(f"pykrx unavailable for {trade_date}")
        return self._bars_by_date.get(trade_date, [])


class _StubIndexPriceDataSource:
    def __init__(self, bars_by_date: dict[date, list[IndexPriceInfo]]) -> None:
        self._bars_by_date = bars_by_date

    async def get_daily_ohlcv(self, trade_date: date) -> list[IndexPriceInfo]:
        return self._bars_by_date.get(trade_date, [])


class _PeriodAwareFinancialStatementDataSource:
    def __init__(
        self,
        statements_by_period: dict[tuple[int, FiscalQuarter], list[FinancialStatementInfo]],
        systemic_error_period: tuple[int, FiscalQuarter],
    ) -> None:
        self._statements_by_period = statements_by_period
        self._systemic_error_period = systemic_error_period
        self.requested_periods: list[tuple[int, FiscalQuarter]] = []

    async def get_quarterly_statements(
        self, tickers: list[str], fiscal_year: int, fiscal_quarter: FiscalQuarter
    ) -> list[FinancialStatementInfo]:
        period = (fiscal_year, fiscal_quarter)
        self.requested_periods.append(period)
        if period == self._systemic_error_period:
            raise DartSystemicError("registered key rejected")
        return self._statements_by_period.get(period, [])


def _price_bar(ticker: str, trade_date: date, close: int = 71_200) -> DailyPriceInfo:
    return DailyPriceInfo(
        ticker=ticker,
        date=trade_date,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        adjusted_close=Decimal(close),
        volume=1_000,
        trading_value=Decimal(close * 1_000),
    )


def _index_bar(index_code: IndexCode, trade_date: date, close: int = 2_665) -> IndexPriceInfo:
    return IndexPriceInfo(
        index_code=index_code,
        date=trade_date,
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=1_000,
        trading_value=Decimal(close * 1_000),
    )


def _statement(
    ticker: str, fiscal_year: int, fiscal_quarter: FiscalQuarter
) -> FinancialStatementInfo:
    return FinancialStatementInfo(
        ticker=ticker,
        fiscal_year=fiscal_year,
        fiscal_quarter=fiscal_quarter,
        consolidated_type=ConsolidatedType.CFS,
        revenue=Decimal(1_000),
        operating_income=Decimal(200),
        net_income=Decimal(150),
        total_assets=Decimal(5_000),
        total_liabilities=Decimal(2_000),
        total_equity=Decimal(3_000),
        disclosed_at=date(fiscal_year, 3, 31),
        rcept_no=f"{fiscal_year}0331{ticker}",
    )


async def _seed_active_asset(asset_repo: FakeAssetRepository, ticker: str) -> None:
    await asset_repo.upsert_active(
        ticker=ticker,
        name="Test Asset",
        market=Market.KR,
        asset_type=AssetType.STOCK,
        exchange=Exchange.KOSPI,
    )


def test_backfill_market_data_syncs_every_trading_day() -> None:
    asset_repo = FakeAssetRepository()
    price_repo = FakeMarketPriceRepository()
    index_repo = FakeIndexPriceRepository()
    asyncio.run(_seed_active_asset(asset_repo, "005930"))
    trading_days = [date(2026, 7, 27), date(2026, 7, 28), date(2026, 7, 29)]
    price_source = _StubPriceDataSource({d: [_price_bar("005930", d)] for d in trading_days})
    index_source = _StubIndexPriceDataSource(
        {d: [_index_bar(IndexCode.KOSPI, d)] for d in trading_days}
    )

    result = asyncio.run(
        backfill_market_data(
            price_source, asset_repo, price_repo, index_source, index_repo, trading_days
        )
    )

    assert result.prices_synced == 3
    assert result.index_prices_synced == 3
    assert result.failed_dates == ()
    assert len(price_repo.prices) == 3
    assert len(index_repo.prices) == 3


def test_backfill_market_data_isolates_single_day_failure() -> None:
    asset_repo = FakeAssetRepository()
    price_repo = FakeMarketPriceRepository()
    index_repo = FakeIndexPriceRepository()
    asyncio.run(_seed_active_asset(asset_repo, "005930"))
    trading_days = [date(2026, 7, 27), date(2026, 7, 28), date(2026, 7, 29)]
    failing_day = date(2026, 7, 28)
    price_source = _StubPriceDataSource(
        {d: [_price_bar("005930", d)] for d in trading_days},
        failing_dates=frozenset({failing_day}),
    )
    index_source = _StubIndexPriceDataSource(
        {d: [_index_bar(IndexCode.KOSPI, d)] for d in trading_days}
    )

    result = asyncio.run(
        backfill_market_data(
            price_source, asset_repo, price_repo, index_source, index_repo, trading_days
        )
    )

    assert result.failed_dates == (failing_day,)
    assert result.prices_synced == 2
    # The two non-failing days still synced their index bar too.
    assert result.index_prices_synced == 2
    assert {p.date for p in price_repo.prices} == {date(2026, 7, 27), date(2026, 7, 29)}


def test_backfill_market_data_rerun_is_idempotent() -> None:
    asset_repo = FakeAssetRepository()
    price_repo = FakeMarketPriceRepository()
    index_repo = FakeIndexPriceRepository()
    asyncio.run(_seed_active_asset(asset_repo, "005930"))
    trading_days = [date(2026, 7, 27), date(2026, 7, 28)]
    price_source = _StubPriceDataSource({d: [_price_bar("005930", d)] for d in trading_days})
    index_source = _StubIndexPriceDataSource(
        {d: [_index_bar(IndexCode.KOSPI, d)] for d in trading_days}
    )

    asyncio.run(
        backfill_market_data(
            price_source, asset_repo, price_repo, index_source, index_repo, trading_days
        )
    )
    result = asyncio.run(
        backfill_market_data(
            price_source, asset_repo, price_repo, index_source, index_repo, trading_days
        )
    )

    assert result.prices_synced == 2
    assert result.index_prices_synced == 2
    # Re-running over the same date range must update rows in place, not
    # duplicate them (existing (asset_id, date)/(index_code, date) PKs).
    assert len(price_repo.prices) == 2
    assert len(index_repo.prices) == 2


def test_backfill_financial_statements_syncs_every_period() -> None:
    asset_repo = FakeAssetRepository()
    statement_repo = FakeFinancialStatementRepository()
    asyncio.run(_seed_active_asset(asset_repo, "005930"))
    fiscal_periods = [(2023, FiscalQuarter.ANNUAL), (2024, FiscalQuarter.ANNUAL)]
    source = _PeriodAwareFinancialStatementDataSource(
        statements_by_period={
            (2023, FiscalQuarter.ANNUAL): [_statement("005930", 2023, FiscalQuarter.ANNUAL)],
            (2024, FiscalQuarter.ANNUAL): [_statement("005930", 2024, FiscalQuarter.ANNUAL)],
        },
        systemic_error_period=(9999, FiscalQuarter.ANNUAL),
    )

    result = asyncio.run(
        backfill_financial_statements(source, asset_repo, statement_repo, fiscal_periods)
    )

    assert result.synced == 2
    assert result.periods_processed == 2
    assert len(statement_repo.statements) == 2


def test_backfill_financial_statements_aborts_batch_on_dart_systemic_error() -> None:
    """DartSystemicError must propagate and stop remaining periods (issue #50/#51 contract)."""
    asset_repo = FakeAssetRepository()
    statement_repo = FakeFinancialStatementRepository()
    asyncio.run(_seed_active_asset(asset_repo, "005930"))
    fiscal_periods = [
        (2023, FiscalQuarter.ANNUAL),
        (2024, FiscalQuarter.ANNUAL),
        (2025, FiscalQuarter.ANNUAL),
    ]
    source = _PeriodAwareFinancialStatementDataSource(
        statements_by_period={
            (2023, FiscalQuarter.ANNUAL): [_statement("005930", 2023, FiscalQuarter.ANNUAL)],
        },
        systemic_error_period=(2024, FiscalQuarter.ANNUAL),
    )

    with pytest.raises(DartSystemicError):
        asyncio.run(
            backfill_financial_statements(source, asset_repo, statement_repo, fiscal_periods)
        )

    # 2023 synced before the systemic error; 2025 must never have been requested.
    assert len(statement_repo.statements) == 1
    assert source.requested_periods == [(2023, FiscalQuarter.ANNUAL), (2024, FiscalQuarter.ANNUAL)]
