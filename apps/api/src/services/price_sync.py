"""Daily OHLCV sync service (SoT A6.1(2)/C1/C3 — services layer).

``sync_prices`` is the wiring ``src/domain/market_price.py`` deferred: it
turns a ``PriceDataSource.get_daily_ohlcv()`` snapshot (ticker-keyed) into
``market_prices`` rows (``asset_id``-keyed) via ``AssetRepository`` +
``MarketPriceRepository.upsert``, the same pattern
``src.services.asset_sync.sync_assets`` uses for ``assets``. Running this on
a schedule (Arq ``collect_prices``, SoT D6) and recording ``job_runs`` are
later issues' scope — this one only does the per-run upsert.
"""

from __future__ import annotations

from datetime import date
from typing import NamedTuple

from src.domain.asset import AssetRepository, Market
from src.domain.market_price import MarketPriceRepository, PriceDataSource


class SyncPricesResult(NamedTuple):
    synced: int
    skipped_tickers: tuple[str, ...]


async def sync_prices(
    data_source: PriceDataSource,
    asset_repo: AssetRepository,
    price_repo: MarketPriceRepository,
    trade_date: date,
) -> SyncPricesResult:
    """Upsert every bar from ``data_source`` into ``price_repo``; report what was skipped.

    A bar whose ``ticker`` has no active row in ``asset_repo`` is skipped
    rather than raising — this keeps a not-yet-synced ticker from tripping
    the ``market_prices.asset_id`` FK, and assumes the normal operating
    order (SoT D6: ticker-master sync runs before ``collect_prices``) rather
    than treating the gap as an error. Like ``sync_assets``, every ticker is
    looked up under ``Market.KR``, the only market this data source covers
    today.
    """
    bars = await data_source.get_daily_ohlcv(trade_date)
    synced = 0
    skipped: list[str] = []
    for bar in bars:
        asset = await asset_repo.get_active_by_ticker(bar.ticker, Market.KR)
        if asset is None:
            skipped.append(bar.ticker)
            continue
        await price_repo.upsert(asset_id=asset.id, bar=bar)
        synced += 1
    return SyncPricesResult(synced=synced, skipped_tickers=tuple(skipped))
