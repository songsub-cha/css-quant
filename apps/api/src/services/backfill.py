"""Historical backfill orchestration (SoT C2/A6.7.6 — services layer).

C2 requires backfill and incremental collection to run through the same
code path, so this module does no independent fetching of its own — it
only drives ``src.services.price_sync.sync_prices``,
``src.services.index_price_sync.sync_index_prices``, and
``src.services.financial_statement_sync.sync_financial_statements`` across a
caller-supplied sequence of trading days / fiscal periods, one call per
unit. Trading-day computation (``src.adapters.trading_calendar``) is left to
the caller (``src.workers.backfill_cli``) rather than done inside this
module, mirroring how the three ``sync_*`` functions themselves take an
already-resolved date/fiscal period rather than computing one — this keeps
the orchestration testable with a plain list of dates, no calendar mocking
required.

Failure handling differs by data kind, matching the fail-closed contract
each ``sync_*`` function already established:

- Price/index backfill (``backfill_market_data``) treats one trading day as
  a unit — any exception raised while syncing that day (from either call)
  is caught, logged, and recorded in ``failed_dates`` so the remaining days
  still run (SoT C2 "실패 시 기록"). Whatever that day's ``sync_prices``
  already upserted before the failure stays committed; only the day's
  return-value counts are dropped, which only affects this call's summary,
  not persisted data.
- Financial-statement backfill (``backfill_financial_statements``) never
  catches ``DartSystemicError`` — the same fail-closed contract issue
  #50/#51 established for ``sync_financial_statements`` applies unchanged to
  a backfill run: a systemic DART failure aborts the whole batch rather than
  silently skipping periods.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date
from typing import NamedTuple

from src.domain.asset import AssetRepository
from src.domain.financial_statement import (
    FinancialStatementDataSource,
    FinancialStatementRepository,
    FiscalQuarter,
)
from src.domain.index_price import IndexPriceDataSource, IndexPriceRepository
from src.domain.market_price import MarketPriceRepository, PriceDataSource
from src.services.financial_statement_sync import sync_financial_statements
from src.services.index_price_sync import sync_index_prices
from src.services.price_sync import sync_prices

logger = logging.getLogger(__name__)


class BackfillMarketDataResult(NamedTuple):
    prices_synced: int
    index_prices_synced: int
    failed_dates: tuple[date, ...]


async def backfill_market_data(
    price_data_source: PriceDataSource,
    asset_repo: AssetRepository,
    price_repo: MarketPriceRepository,
    index_data_source: IndexPriceDataSource,
    index_price_repo: IndexPriceRepository,
    trading_days: Sequence[date],
) -> BackfillMarketDataResult:
    """Sync prices + index prices for every day in ``trading_days``, isolating per-day failures."""
    prices_synced = 0
    index_prices_synced = 0
    failed_dates: list[date] = []
    for trading_day in trading_days:
        try:
            price_result = await sync_prices(price_data_source, asset_repo, price_repo, trading_day)
            index_result = await sync_index_prices(index_data_source, index_price_repo, trading_day)
        except Exception:  # noqa: BLE001 - per-day isolation boundary, SoT C2
            logger.warning(
                "Market data backfill failed for trading_day=%s; continuing with remaining days",
                trading_day,
                exc_info=True,
            )
            failed_dates.append(trading_day)
            continue
        prices_synced += price_result.synced
        index_prices_synced += index_result.synced
    return BackfillMarketDataResult(
        prices_synced=prices_synced,
        index_prices_synced=index_prices_synced,
        failed_dates=tuple(failed_dates),
    )


class BackfillFinancialStatementsResult(NamedTuple):
    synced: int
    periods_processed: int


async def backfill_financial_statements(
    data_source: FinancialStatementDataSource,
    asset_repo: AssetRepository,
    financial_statement_repo: FinancialStatementRepository,
    fiscal_periods: Sequence[tuple[int, FiscalQuarter]],
) -> BackfillFinancialStatementsResult:
    """Sync financial statements for every ``(fiscal_year, fiscal_quarter)`` in ``fiscal_periods``.

    ``DartSystemicError`` is deliberately not caught here — see the module
    docstring. It propagates out of ``sync_financial_statements`` and aborts
    the remaining periods.
    """
    synced = 0
    for fiscal_year, fiscal_quarter in fiscal_periods:
        result = await sync_financial_statements(
            data_source, asset_repo, financial_statement_repo, fiscal_year, fiscal_quarter
        )
        synced += result.synced
    return BackfillFinancialStatementsResult(synced=synced, periods_processed=len(fiscal_periods))
