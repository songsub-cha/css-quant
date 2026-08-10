"""Arq cron task entrypoints wiring ``sync_assets``/``sync_prices`` into ``job_runs`` (SoT D6).

Each task opens its own session from ``ctx["session_maker"]`` (set by
``WorkerSettings.on_startup``), builds the repositories/lock, and delegates
the lock -> ``start_job_run`` -> service -> ``finish_job_run`` orchestration
to ``src.services.job_run.run_locked_job``. Data sources come from
``ctx["data_source"]``/``ctx["price_data_source"]`` — the ``DATA_SOURCE``-selected
adapter pair ``WorkerSettings.on_startup`` builds via
``build_data_sources_on_startup`` (SoT B3) — rather than a hardcoded
concrete adapter, so these tasks pick up real pykrx adapters under
``DATA_SOURCE=krx`` the same way the rest of the worker does.

``run_date`` is today's date in KST, not UTC: the cron schedule itself is
designed around KST wall-clock trading hours (see ``WorkerSettings``), so
the run this task belongs to is the KST trading day it fires within.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.adapters.asset_repository import SqlAlchemyAssetRepository
from src.adapters.job_lock import RedisJobLock
from src.adapters.job_run_repository import SqlAlchemyJobRunRepository
from src.adapters.market_price_repository import SqlAlchemyMarketPriceRepository
from src.services.asset_sync import sync_assets
from src.services.job_run import run_locked_job
from src.services.price_sync import sync_prices

# Comfortably longer than each cron job's own 300s timeout (SoT
# WorkerSettings.cron_jobs) so the lock can never expire out from under a
# still-running task and let a second run start early.
_LOCK_TTL_SECONDS = 600
_KST = ZoneInfo("Asia/Seoul")


async def sync_asset_master_task(ctx: dict[str, Any]) -> None:
    async with ctx["session_maker"]() as session:
        asset_repo = SqlAlchemyAssetRepository(session)
        job_run_repo = SqlAlchemyJobRunRepository(session)
        lock = RedisJobLock(ctx["redis"])
        data_source = ctx["data_source"]

        async def _work() -> dict[str, Any]:
            count = await sync_assets(data_source, asset_repo)
            return {"synced": count}

        await run_locked_job(
            job_run_repo,
            lock,
            job_name="sync_asset_master",
            run_date=datetime.now(_KST).date(),
            lock_ttl_seconds=_LOCK_TTL_SECONDS,
            work=_work,
        )


async def collect_prices_task(ctx: dict[str, Any]) -> None:
    async with ctx["session_maker"]() as session:
        asset_repo = SqlAlchemyAssetRepository(session)
        price_repo = SqlAlchemyMarketPriceRepository(session)
        job_run_repo = SqlAlchemyJobRunRepository(session)
        lock = RedisJobLock(ctx["redis"])
        data_source = ctx["price_data_source"]
        trade_date = datetime.now(_KST).date()

        async def _work() -> dict[str, Any]:
            result = await sync_prices(data_source, asset_repo, price_repo, trade_date)
            return {"synced": result.synced, "skipped_tickers": list(result.skipped_tickers)}

        await run_locked_job(
            job_run_repo,
            lock,
            job_name="collect_prices",
            run_date=trade_date,
            lock_ttl_seconds=_LOCK_TTL_SECONDS,
            work=_work,
        )
