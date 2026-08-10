"""Arq worker boot entrypoint (SoT D1 — worker must never be missing from compose).

Like ``alembic/env.py``, this file is a process entrypoint rather than
application logic living in the ``workers`` layer, so it is one of the few
places allowed to import ``src.config`` directly (see the docstring in
``src/config.py``). It composes ``Settings()`` the same way
``alembic/env.py`` does — no ``api/deps.get_settings`` — so no
``workers -> api`` edge is introduced (SoT B2).

``cron_jobs`` schedules the two Phase 2 jobs (SoT D6): ``sync_asset_master``
at UTC 07:20 (KST 16:20) and ``collect_prices`` at UTC 07:30 (KST 16:30),
``weekday`` Mon-Fri. This KST/UTC equality holds only for these two times of
day — the rest of D6's schedule sits at other UTC offsets (e.g. KST early
morning wraps to the *previous* UTC day) and needs its own per-job check
when those jobs are added.

``on_startup`` does two things into ``ctx``: it builds/stashes the DB engine
and an ``async_sessionmaker`` (the same ``Settings()``-composes-its-own-engine
pattern ``api/deps.py`` uses, just without routing through it — that would
create the forbidden ``workers -> api`` edge noted above) for the tasks to
open sessions from, and it delegates to ``build_data_sources_on_startup`` to
build the ``DataSource``/``PriceDataSource``/``IndexPriceDataSource``/
``FinancialStatementDataSource`` adapter set selected by ``Settings.data_source``
(SoT B3), so task functions read ``ctx["data_source"]``/
``ctx["price_data_source"]``/``ctx["index_price_data_source"]``/
``ctx["financial_statement_data_source"]`` instead of hardcoding a concrete
adapter. This composition happens here rather than ``api/deps.py`` because
the worker process — not the API process — is what runs the collection jobs
that consume these adapters (SoT D6). ``on_shutdown`` disposes the engine.

``DATA_SOURCE=krx`` with an empty ``DART_API_KEY`` fails the worker at boot
(fail-closed) rather than silently wiring a fake financial-statement source
alongside real pykrx adapters — same rationale as ``cookie_secure``/
``secret_key`` having no Python-level default (SoT 원칙 8). A wrong or
expired key passes this boot-time check but fails on the first API call,
inside ``DartFinancialStatementDataSource`` (raises ``DartSystemicError`` —
see ``src/adapters/dart_financial_data_source.py``).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from arq.connections import RedisSettings
from arq.cron import CronJob, cron
from arq.typing import StartupShutdown, WorkerCoroutine
from arq.worker import Function
from sqlalchemy.ext.asyncio import async_sessionmaker

from src.adapters.dart_financial_data_source import (
    DartFinancialStatementDataSource,
    FakeFinancialStatementDataSource,
)
from src.adapters.data_sources import (
    FakeDataSource,
    FakeIndexPriceDataSource,
    FakePriceDataSource,
    PykrxDataSource,
    PykrxIndexPriceDataSource,
    PykrxPriceDataSource,
)
from src.adapters.db import get_engine
from src.config import Settings
from src.workers.tasks import collect_prices_task, sync_asset_master_task


def build_redis_settings(redis_url: str) -> RedisSettings:
    """Pure DSN -> RedisSettings conversion, kept separate from Settings() for testing."""
    return RedisSettings.from_dsn(redis_url)


async def build_data_sources_on_startup(ctx: dict[str, Any]) -> None:
    """Populate ``ctx`` with the ``DATA_SOURCE``-selected adapter pair (SoT B3)."""
    # cookie_secure/secret_key have no Python-level default (see the
    # module-level Settings() call below for the same gap).
    settings = Settings()  # type: ignore[call-arg]
    if settings.data_source == "krx":
        if not settings.dart_api_key:
            raise RuntimeError(
                "DATA_SOURCE=krx requires DART_API_KEY to be set (fail-closed;"
                " see src/workers/settings.py)"
            )
        ctx["data_source"] = PykrxDataSource()
        ctx["price_data_source"] = PykrxPriceDataSource()
        ctx["index_price_data_source"] = PykrxIndexPriceDataSource()
        ctx["financial_statement_data_source"] = DartFinancialStatementDataSource(
            settings.dart_api_key
        )
    else:
        ctx["data_source"] = FakeDataSource()
        ctx["price_data_source"] = FakePriceDataSource()
        ctx["index_price_data_source"] = FakeIndexPriceDataSource()
        ctx["financial_statement_data_source"] = FakeFinancialStatementDataSource()


async def startup(ctx: dict[str, Any]) -> None:
    engine = get_engine(Settings().database_url)  # type: ignore[call-arg]
    ctx["engine"] = engine
    ctx["session_maker"] = async_sessionmaker(engine, expire_on_commit=False)
    await build_data_sources_on_startup(ctx)


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["engine"].dispose()


class WorkerSettings:
    # Explicit annotations matching arq.typing.WorkerSettingsBase exactly are
    # required: mypy strict checks type[WorkerSettings] against that Protocol
    # invariantly, so inferred (narrower) attribute types — or omitting an
    # attribute that has a Protocol-level default — both fail the match.
    functions: Sequence[WorkerCoroutine | Function] = [
        sync_asset_master_task,
        collect_prices_task,
    ]
    cron_jobs: Sequence[CronJob] | None = [
        # weekday is a set of ints (Mon=0 .. Sun=6) — arq's weekday matcher
        # does not accept a set of weekday-name strings (only a single
        # Literal name or int/set[int]); a string set silently never
        # matches and crashes worker boot with OverflowError.
        cron(
            sync_asset_master_task,
            hour=7,
            minute=20,  # KST 16:20 — must precede collect_prices (SoT D6)
            weekday={0, 1, 2, 3, 4},
            timeout=300,
        ),
        cron(
            collect_prices_task,
            hour=7,
            minute=30,  # KST 16:30 — daily OHLCV collection (SoT D6)
            weekday={0, 1, 2, 3, 4},
            timeout=300,
        ),
    ]
    on_startup: StartupShutdown | None = startup
    on_shutdown: StartupShutdown | None = shutdown
    # cookie_secure (SoT D2) has no Python-level default — it's loaded from
    # the environment/.env at runtime by BaseSettings. mypy can't see that
    # binding and statically demands the kwarg; see api/deps.py for the
    # same gap.
    redis_settings = build_redis_settings(Settings().redis_url)  # type: ignore[call-arg]
