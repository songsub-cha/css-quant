"""Ticker master sync service (SoT C1/C2/C3 — services layer).

``sync_assets`` turns a ``DataSource.list_tickers()`` snapshot into
``assets`` rows via ``AssetRepository.upsert_active``. Recording
``job_runs`` and detecting delistings from tickers that drop out of the
snapshot are later issues' scope — this one only does the per-run upsert.
"""

from __future__ import annotations

from src.domain.asset import AssetRepository, DataSource, Market


async def sync_assets(data_source: DataSource, asset_repo: AssetRepository) -> int:
    """Upsert every ticker from ``data_source`` into ``asset_repo``; return the count processed.

    Every row uses ``Market.KR``, the only market this data source covers
    today; ``asset_type`` (STOCK/ETF) comes from ``TickerInfo`` itself.
    """
    tickers = await data_source.list_tickers()
    for ticker in tickers:
        await asset_repo.upsert_active(
            ticker=ticker.ticker,
            name=ticker.name,
            market=Market.KR,
            asset_type=ticker.asset_type,
            exchange=ticker.exchange,
        )
    return len(tickers)
