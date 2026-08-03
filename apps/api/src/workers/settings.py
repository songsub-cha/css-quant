"""Arq worker boot entrypoint (SoT D1 — worker must never be missing from compose).

Like ``alembic/env.py``, this file is a process entrypoint rather than
application logic living in the ``workers`` layer, so it is one of the few
places allowed to import ``src.config`` directly (see the docstring in
``src/config.py``). It composes ``Settings()`` the same way
``alembic/env.py`` does — no ``api/deps.get_settings`` — so no
``workers -> api`` edge is introduced (SoT B2).

No real jobs are registered yet — ``functions`` holds a single no-op
``healthcheck`` task so ``arq.worker.Worker.__init__`` (which raises
``RuntimeError`` when ``functions`` and ``cron_jobs`` are both empty) does
not reject the worker before it even gets a chance to connect to Redis.
This only proves the worker process can boot and connect to Redis; real
jobs land in Phase 2+.

``on_startup`` builds the ``DataSource``/``PriceDataSource``/
``IndexPriceDataSource``/``FinancialStatementDataSource`` adapter set
selected by ``Settings.data_source`` (SoT B3) into ``ctx``, so task functions
(added in a later issue) read ``ctx["data_source"]``/
``ctx["price_data_source"]``/``ctx["index_price_data_source"]``/
``ctx["financial_statement_data_source"]`` instead of hardcoding a concrete
adapter. This composition happens here rather than ``api/deps.py`` because
the worker process — not the API process — is what runs the collection jobs
that consume these adapters (SoT D6). ``cron_jobs``/``functions`` are
untouched — scheduling the KOSPI/VKOSPI collection job is issue #39/PR #40's
scope.

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
from arq.cron import CronJob
from arq.typing import StartupShutdown, WorkerCoroutine
from arq.worker import Function

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
from src.config import Settings


def build_redis_settings(redis_url: str) -> RedisSettings:
    """Pure DSN -> RedisSettings conversion, kept separate from Settings() for testing."""
    return RedisSettings.from_dsn(redis_url)


async def healthcheck(ctx: dict[str, Any]) -> str:
    """No-op task that only exists to satisfy arq's non-empty functions requirement."""
    return "ok"


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


class WorkerSettings:
    # Explicit annotations matching arq.typing.WorkerSettingsBase exactly are
    # required: mypy strict checks type[WorkerSettings] against that Protocol
    # invariantly, so inferred (narrower) attribute types — or omitting an
    # attribute that has a Protocol-level default — both fail the match.
    functions: Sequence[WorkerCoroutine | Function] = [healthcheck]
    cron_jobs: Sequence[CronJob] | None = None
    on_startup: StartupShutdown | None = build_data_sources_on_startup
    on_shutdown: StartupShutdown | None = None
    # cookie_secure (SoT D2) has no Python-level default — it's loaded from
    # the environment/.env at runtime by BaseSettings. mypy can't see that
    # binding and statically demands the kwarg; see api/deps.py for the
    # same gap.
    redis_settings = build_redis_settings(Settings().redis_url)  # type: ignore[call-arg]
