"""Ticker master sync service (SoT C1/C2/C3 — services layer).

``sync_assets`` is the wiring the SoT A8 Phase 2 completion bar and issue
#27's "범위 제외" both deferred: it turns a ``DataSource.list_tickers()``
snapshot into ``assets`` rows via ``AssetRepository.upsert_active``. Running
this on a schedule and recording ``job_runs`` is now wired via
``src.workers.tasks.sync_asset_master_task``/``src.services.job_run.run_locked_job``
(SoT D6) — detecting delistings from tickers that drop out of the snapshot
remains a later issue's scope; this function itself only does the per-run
upsert.
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
