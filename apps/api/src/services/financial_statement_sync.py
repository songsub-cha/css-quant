"""DART quarterly financial statement sync service (SoT C1/A6.1/A6.7.2 — services layer).

``sync_financial_statements`` is the wiring ``src/domain/financial_statement.py``
deferred — same shape as ``src.services.price_sync.sync_prices``: fetch by
ticker, map to ``asset_id`` via ``AssetRepository``, upsert. STOCK-only
scoping comes from what is passed *into* ``data_source.get_quarterly_statements`` —
``asset_repo.list_active(market=Market.KR, asset_type=AssetType.STOCK)``
never includes ETF tickers in the first place, so ETFs are excluded
structurally rather than by filtering the result (same approach
``PykrxPriceDataSource`` uses to keep market cap off ETF bars, ADR 0011).

``DartSystemicError`` (raised by ``DartFinancialStatementDataSource`` on an
auth/quota/maintenance-level DART status) is never caught here — it
propagates out of ``data_source.get_quarterly_statements`` so this function
never returns a partial result silently after a systemic failure; the caller
(later cron wiring, issue #39/#40) sees the exception. Scheduling this on a
quarterly disclosure cadence and recording ``job_runs`` are that issue's scope
too — this one only does the per-run upsert.
"""

from __future__ import annotations

from typing import NamedTuple

from src.domain.asset import AssetRepository, AssetType, Market
from src.domain.financial_statement import (
    FinancialStatementDataSource,
    FinancialStatementRepository,
    FiscalQuarter,
)


class SyncFinancialStatementsResult(NamedTuple):
    synced: int
    skipped_tickers: tuple[str, ...]


async def sync_financial_statements(
    data_source: FinancialStatementDataSource,
    asset_repo: AssetRepository,
    financial_statement_repo: FinancialStatementRepository,
    fiscal_year: int,
    fiscal_quarter: FiscalQuarter,
) -> SyncFinancialStatementsResult:
    """Upsert every statement ``data_source`` returns; report what was skipped.

    A statement whose ``ticker`` has no matching row in ``asset_repo`` (it
    was requested but not found — an inconsistent state, since only tickers
    already in ``assets`` are ever requested) is skipped rather than raising,
    mirroring ``sync_prices``'s regard for ticker/asset_id mismatches.
    """
    assets = await asset_repo.list_active(market=Market.KR, asset_type=AssetType.STOCK)
    asset_by_ticker = {asset.ticker: asset for asset in assets}

    statements = await data_source.get_quarterly_statements(
        list(asset_by_ticker.keys()), fiscal_year, fiscal_quarter
    )

    synced = 0
    skipped: list[str] = []
    for statement in statements:
        asset = asset_by_ticker.get(statement.ticker)
        if asset is None:
            skipped.append(statement.ticker)
            continue
        await financial_statement_repo.upsert(asset_id=asset.id, statement=statement)
        synced += 1
    return SyncFinancialStatementsResult(synced=synced, skipped_tickers=tuple(skipped))
