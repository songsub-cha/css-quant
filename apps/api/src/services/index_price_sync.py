"""KOSPI/VKOSPI index daily OHLCV sync service (SoT A6.2/A6.3 — services layer).

``sync_index_prices`` is the wiring ``src/domain/index_price.py`` deferred —
same role as ``src.services.price_sync.sync_prices``, but simpler: an index
bar upserts directly by ``index_code`` with no ``AssetRepository`` lookup/
skip step, since ``index_prices`` has no ``assets`` FK to satisfy. Running
this on a schedule (Arq cron, SoT D6) and recording ``job_runs`` are out of
scope — issue #39/PR #40 (cron wiring) already owns that, and ``sync_prices``
itself isn't ``job_runs``-wired yet either.
"""

from __future__ import annotations

from datetime import date
from typing import NamedTuple

from src.domain.index_price import IndexPriceDataSource, IndexPriceRepository


class SyncIndexPricesResult(NamedTuple):
    synced: int


async def sync_index_prices(
    data_source: IndexPriceDataSource,
    index_price_repo: IndexPriceRepository,
    trade_date: date,
) -> SyncIndexPricesResult:
    """Upsert every bar ``data_source`` returns into ``index_price_repo``."""
    bars = await data_source.get_daily_ohlcv(trade_date)
    for bar in bars:
        await index_price_repo.upsert(bar=bar)
    return SyncIndexPricesResult(synced=len(bars))
