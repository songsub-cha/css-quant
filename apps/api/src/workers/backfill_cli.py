"""One-off historical backfill entrypoint (SoT C2/A6.7.6 — process entrypoint).

Like ``alembic/env.py`` and ``src/workers/settings.py``, this is a process
entrypoint rather than application logic living in the ``workers`` layer —
run once (``python -m src.workers.backfill_cli ...``), not scheduled — so it
is one of the few places allowed to import ``src.config`` directly (see the
docstring in ``src/config.py``).

C2's "백필과 운영 산출은 같은 코드 경로" principle means this file adds no new
collection logic of its own: ``resolve_backfill_plan`` only turns CLI args
into a trading-day list (``src.adapters.trading_calendar``) and a
``(fiscal_year, fiscal_quarter)`` list, and ``execute_backfill`` only calls
``src.services.backfill.backfill_market_data``/``backfill_financial_statements``
— the same ``sync_prices``/``sync_index_prices``/``sync_financial_statements``
wiring the daily incremental path will eventually use (issue #39/#40's cron
wiring, out of this issue's scope).

``execute_backfill`` takes every data source/repository as an already-built
dependency (Protocol-typed, like every ``sync_*`` service) rather than
constructing them itself — this is what makes it testable end-to-end with
the in-memory fakes ``tests/conftest.py`` already provides, with no live DB
(none exists in this environment; see ``tests/conftest.py``'s module
docstring). Only ``main_async`` — the real entrypoint — builds the concrete
``DATA_SOURCE``-selected adapters and a live DB session, mirroring
``src.workers.settings.build_data_sources_on_startup``'s branching (kept
duplicated rather than shared: that function is arq's boot hook and takes an
arq ``ctx`` dict, a shape specific to the worker process this file is not).

Asset-master backfill (past ticker-master snapshots, delisted-ticker
reconstruction) is out of scope — see the issue's "제외" section; only
prices/index prices/financial statements are backfilled here.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from collections.abc import Sequence
from datetime import date, timedelta
from typing import NamedTuple

from sqlalchemy.ext.asyncio import async_sessionmaker

from src.adapters.asset_repository import SqlAlchemyAssetRepository
from src.adapters.dart_financial_data_source import (
    DartFinancialStatementDataSource,
    FakeFinancialStatementDataSource,
)
from src.adapters.data_sources import (
    FakeIndexPriceDataSource,
    FakePriceDataSource,
    PykrxIndexPriceDataSource,
    PykrxPriceDataSource,
)
from src.adapters.db import get_engine
from src.adapters.financial_statement_repository import SqlAlchemyFinancialStatementRepository
from src.adapters.index_price_repository import SqlAlchemyIndexPriceRepository
from src.adapters.market_price_repository import SqlAlchemyMarketPriceRepository
from src.adapters.trading_calendar import get_krx_trading_days
from src.config import Settings
from src.domain.asset import AssetRepository
from src.domain.financial_statement import (
    FinancialStatementDataSource,
    FinancialStatementRepository,
    FiscalQuarter,
)
from src.domain.index_price import IndexPriceDataSource, IndexPriceRepository
from src.domain.market_price import MarketPriceRepository, PriceDataSource
from src.services.backfill import backfill_financial_statements, backfill_market_data

logger = logging.getLogger(__name__)

# SoT C2: "히스토리 백필(최소 2015년~)".
_DEFAULT_START_DATE = date(2015, 1, 1)
_DEFAULT_FISCAL_START_YEAR = 2015


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "One-off historical backfill for market prices, index prices, and financial"
            " statements (SoT C2). Not scheduled — run manually once per environment."
        )
    )
    parser.add_argument(
        "--target",
        choices=["prices", "financials", "all"],
        default="all",
        help="Which data to backfill (default: all).",
    )
    parser.add_argument(
        "--start-date",
        type=date.fromisoformat,
        default=_DEFAULT_START_DATE,
        help="First trading day to backfill prices/index prices for (default: 2015-01-01).",
    )
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=None,
        help="Last trading day to backfill (default: yesterday).",
    )
    parser.add_argument(
        "--fiscal-start-year",
        type=int,
        default=_DEFAULT_FISCAL_START_YEAR,
        help="First fiscal year to backfill financial statements for (default: 2015).",
    )
    parser.add_argument(
        "--fiscal-end-year",
        type=int,
        default=None,
        help="Last fiscal year to backfill (default: current year).",
    )
    return parser.parse_args(list(argv))


class BackfillPlan(NamedTuple):
    trading_days: list[date]
    fiscal_periods: list[tuple[int, FiscalQuarter]]


def resolve_backfill_plan(args: argparse.Namespace, today: date) -> BackfillPlan:
    """Turn parsed CLI args into a concrete trading-day list + fiscal-period list.

    ``today`` is an explicit parameter (mirroring
    ``PasswordResetTokenRepository.use_token``'s ``now`` parameter) rather
    than read from ``date.today()`` internally, so this stays a pure,
    deterministically testable function.
    """
    end_date = args.end_date if args.end_date is not None else today - timedelta(days=1)
    trading_days = get_krx_trading_days(args.start_date, end_date)

    fiscal_end_year = args.fiscal_end_year if args.fiscal_end_year is not None else today.year
    fiscal_periods = [
        (year, quarter)
        for year in range(args.fiscal_start_year, fiscal_end_year + 1)
        for quarter in FiscalQuarter
    ]
    return BackfillPlan(trading_days=trading_days, fiscal_periods=fiscal_periods)


async def execute_backfill(
    *,
    target: str,
    plan: BackfillPlan,
    price_data_source: PriceDataSource,
    asset_repo: AssetRepository,
    price_repo: MarketPriceRepository,
    index_data_source: IndexPriceDataSource,
    index_price_repo: IndexPriceRepository,
    financial_data_source: FinancialStatementDataSource,
    financial_statement_repo: FinancialStatementRepository,
) -> str:
    """Run the requested backfill target(s) and return a human-readable summary.

    Every dependency is Protocol-typed and passed in already-built — this
    function never constructs an adapter/repository/session itself, so a
    test can call it with ``tests/conftest.py``'s fakes exactly like
    ``tests/test_backfill.py`` does, with no live DB.
    """
    summary_lines: list[str] = []
    if target in ("prices", "all"):
        market_result = await backfill_market_data(
            price_data_source,
            asset_repo,
            price_repo,
            index_data_source,
            index_price_repo,
            plan.trading_days,
        )
        summary_lines.append(
            f"prices: {market_result.prices_synced} bars,"
            f" {market_result.index_prices_synced} index bars synced across"
            f" {len(plan.trading_days)} trading days"
            f" ({len(market_result.failed_dates)} failed: {market_result.failed_dates})"
        )
    if target in ("financials", "all"):
        statement_result = await backfill_financial_statements(
            financial_data_source, asset_repo, financial_statement_repo, plan.fiscal_periods
        )
        summary_lines.append(
            f"financials: {statement_result.synced} statements synced across"
            f" {statement_result.periods_processed} fiscal periods"
        )
    return "\n".join(summary_lines)


async def main_async(argv: Sequence[str]) -> None:
    args = _parse_args(argv)
    plan = resolve_backfill_plan(args, date.today())
    logger.info(
        "Backfill plan: %d trading days, %d fiscal periods (target=%s)",
        len(plan.trading_days),
        len(plan.fiscal_periods),
        args.target,
    )

    # cookie_secure/secret_key have no Python-level default — same gap as
    # api/deps.get_settings()/workers/settings.build_data_sources_on_startup.
    settings = Settings()  # type: ignore[call-arg]
    engine = get_engine(settings.database_url)
    session_maker = async_sessionmaker(engine, expire_on_commit=False)

    if settings.data_source == "krx":
        if not settings.dart_api_key:
            raise RuntimeError(
                "DATA_SOURCE=krx requires DART_API_KEY to be set (fail-closed;"
                " see src/workers/settings.py's build_data_sources_on_startup for the same check)"
            )
        price_data_source: PriceDataSource = PykrxPriceDataSource()
        index_data_source: IndexPriceDataSource = PykrxIndexPriceDataSource()
        financial_data_source: FinancialStatementDataSource = DartFinancialStatementDataSource(
            settings.dart_api_key
        )
    else:
        price_data_source = FakePriceDataSource()
        index_data_source = FakeIndexPriceDataSource()
        financial_data_source = FakeFinancialStatementDataSource()

    async with session_maker() as session:
        summary = await execute_backfill(
            target=args.target,
            plan=plan,
            price_data_source=price_data_source,
            asset_repo=SqlAlchemyAssetRepository(session),
            price_repo=SqlAlchemyMarketPriceRepository(session),
            index_data_source=index_data_source,
            index_price_repo=SqlAlchemyIndexPriceRepository(session),
            financial_data_source=financial_data_source,
            financial_statement_repo=SqlAlchemyFinancialStatementRepository(session),
        )
    logger.info("Backfill complete:\n%s", summary)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main_async(sys.argv[1:]))


if __name__ == "__main__":
    main()
