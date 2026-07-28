"""Ticker master sync service (SoT C1/C2/C3 — services layer).

``sync_assets`` is the wiring the SoT A8 Phase 2 completion bar and issue
#27's "범위 제외" both deferred: it turns a ``DataSource.list_tickers()``
snapshot into ``assets`` rows via ``AssetRepository.upsert_active``. Running
this on a schedule (Arq cron), recording ``job_runs``, and detecting
delistings from tickers that drop out of the snapshot are later issues'
scope — this one only does the per-run upsert.
"""

from __future__ import annotations

from src.domain.asset import AssetRepository, AssetType, DataSource, Market


async def sync_assets(data_source: DataSource, asset_repo: AssetRepository) -> int:
    """Upsert every ticker from ``data_source`` into ``asset_repo``; return the count processed.

    ``TickerInfo`` currently only describes stock tickers (no ``asset_type``
    field), so every row is upserted as ``AssetType.STOCK`` — ETF master
    collection needs its own ``DataSource`` method and is out of scope here.
    Likewise every row uses ``Market.KR``, the only market this data source
    covers today.
    """
    tickers = await data_source.list_tickers()
    for ticker in tickers:
        await asset_repo.upsert_active(
            ticker=ticker.ticker,
            name=ticker.name,
            market=Market.KR,
            asset_type=AssetType.STOCK,
            exchange=ticker.exchange,
        )
    return len(tickers)
