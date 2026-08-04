"""``backfill_cli`` (SoT C2/A6.7.6 — process entrypoint).

``resolve_backfill_plan``/``execute_backfill`` are exercised directly here
with ``tests/conftest.py``'s fakes + ``src.adapters.data_sources``'s/
``src.adapters.dart_financial_data_source``'s ``Fake*DataSource``s — no live
DB, no network, matching how ``DATA_SOURCE=fake`` would run this CLI for
real (``main_async`` only adds DB session + concrete-adapter wiring on top of
these two functions, per the module docstring). Uses ``asyncio.run`` directly
(no pytest-asyncio dependency in this project).
"""

from __future__ import annotations

import asyncio
from datetime import date

from src.adapters.dart_financial_data_source import FakeFinancialStatementDataSource
from src.adapters.data_sources import FakeIndexPriceDataSource, FakePriceDataSource
from src.domain.asset import AssetType, Exchange, Market
from src.domain.financial_statement import FiscalQuarter
from src.workers.backfill_cli import (
    BackfillPlan,
    _parse_args,
    execute_backfill,
    resolve_backfill_plan,
)

from .conftest import (
    FakeAssetRepository,
    FakeFinancialStatementRepository,
    FakeIndexPriceRepository,
    FakeMarketPriceRepository,
)


async def _seed_active_asset(asset_repo: FakeAssetRepository, ticker: str) -> None:
    await asset_repo.upsert_active(
        ticker=ticker,
        name="Test Asset",
        market=Market.KR,
        asset_type=AssetType.STOCK,
        exchange=Exchange.KOSPI,
    )


def test_parse_args_defaults() -> None:
    args = _parse_args([])

    assert args.target == "all"
    assert args.start_date == date(2015, 1, 1)
    assert args.end_date is None
    assert args.fiscal_start_year == 2015
    assert args.fiscal_end_year is None


def test_parse_args_overrides() -> None:
    args = _parse_args(
        [
            "--target",
            "prices",
            "--start-date",
            "2020-01-01",
            "--end-date",
            "2020-01-31",
            "--fiscal-start-year",
            "2019",
            "--fiscal-end-year",
            "2021",
        ]
    )

    assert args.target == "prices"
    assert args.start_date == date(2020, 1, 1)
    assert args.end_date == date(2020, 1, 31)
    assert args.fiscal_start_year == 2019
    assert args.fiscal_end_year == 2021


def test_resolve_backfill_plan_defaults_end_date_to_yesterday_and_fiscal_end_to_this_year() -> None:
    args = _parse_args(["--start-date", "2026-07-27"])
    today = date(2026, 7, 29)

    plan = resolve_backfill_plan(args, today)

    assert plan.trading_days == [date(2026, 7, 27), date(2026, 7, 28)]
    assert plan.fiscal_periods[0] == (2015, FiscalQuarter.Q1)
    assert plan.fiscal_periods[-1] == (2026, FiscalQuarter.ANNUAL)


def test_resolve_backfill_plan_honors_explicit_end_dates() -> None:
    args = _parse_args(
        [
            "--start-date",
            "2026-07-27",
            "--end-date",
            "2026-07-27",
            "--fiscal-start-year",
            "2024",
            "--fiscal-end-year",
            "2024",
        ]
    )

    plan = resolve_backfill_plan(args, date(2026, 7, 29))

    assert plan.trading_days == [date(2026, 7, 27)]
    assert plan.fiscal_periods == [
        (2024, FiscalQuarter.Q1),
        (2024, FiscalQuarter.H1),
        (2024, FiscalQuarter.Q3),
        (2024, FiscalQuarter.ANNUAL),
    ]


def test_execute_backfill_target_all_runs_both_market_and_financial_backfill() -> None:
    asset_repo = FakeAssetRepository()
    asyncio.run(_seed_active_asset(asset_repo, "005930"))
    plan = BackfillPlan(
        trading_days=[date(2026, 7, 29)],
        fiscal_periods=[(2025, FiscalQuarter.ANNUAL)],
    )
    price_repo = FakeMarketPriceRepository()
    index_repo = FakeIndexPriceRepository()
    statement_repo = FakeFinancialStatementRepository()

    summary = asyncio.run(
        execute_backfill(
            target="all",
            plan=plan,
            price_data_source=FakePriceDataSource(),
            asset_repo=asset_repo,
            price_repo=price_repo,
            index_data_source=FakeIndexPriceDataSource(),
            index_price_repo=index_repo,
            financial_data_source=FakeFinancialStatementDataSource(),
            financial_statement_repo=statement_repo,
        )
    )

    assert len(price_repo.prices) > 0
    assert len(index_repo.prices) > 0
    assert len(statement_repo.statements) > 0
    assert "prices:" in summary
    assert "financials:" in summary


def test_execute_backfill_target_prices_skips_financial_backfill() -> None:
    asset_repo = FakeAssetRepository()
    asyncio.run(_seed_active_asset(asset_repo, "005930"))
    plan = BackfillPlan(
        trading_days=[date(2026, 7, 29)],
        fiscal_periods=[(2025, FiscalQuarter.ANNUAL)],
    )
    price_repo = FakeMarketPriceRepository()
    statement_repo = FakeFinancialStatementRepository()

    summary = asyncio.run(
        execute_backfill(
            target="prices",
            plan=plan,
            price_data_source=FakePriceDataSource(),
            asset_repo=asset_repo,
            price_repo=price_repo,
            index_data_source=FakeIndexPriceDataSource(),
            index_price_repo=FakeIndexPriceRepository(),
            financial_data_source=FakeFinancialStatementDataSource(),
            financial_statement_repo=statement_repo,
        )
    )

    assert len(price_repo.prices) > 0
    assert statement_repo.statements == []
    assert "financials:" not in summary


def test_execute_backfill_target_financials_skips_market_backfill() -> None:
    asset_repo = FakeAssetRepository()
    asyncio.run(_seed_active_asset(asset_repo, "005930"))
    plan = BackfillPlan(
        trading_days=[date(2026, 7, 29)],
        fiscal_periods=[(2025, FiscalQuarter.ANNUAL)],
    )
    price_repo = FakeMarketPriceRepository()
    statement_repo = FakeFinancialStatementRepository()

    summary = asyncio.run(
        execute_backfill(
            target="financials",
            plan=plan,
            price_data_source=FakePriceDataSource(),
            asset_repo=asset_repo,
            price_repo=price_repo,
            index_data_source=FakeIndexPriceDataSource(),
            index_price_repo=FakeIndexPriceRepository(),
            financial_data_source=FakeFinancialStatementDataSource(),
            financial_statement_repo=statement_repo,
        )
    )

    assert price_repo.prices == []
    assert len(statement_repo.statements) > 0
    assert "prices:" not in summary
