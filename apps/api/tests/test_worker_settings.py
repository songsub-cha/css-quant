import asyncio
from typing import Any

import pytest
from arq.worker import create_worker

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
from src.workers.settings import WorkerSettings, build_data_sources_on_startup, build_redis_settings
from src.workers.tasks import collect_prices_task, sync_asset_master_task


def test_worker_settings_boots_without_redis() -> None:
    """WorkerSettings must carry at least one function/cron_job or
    arq.worker.Worker.__init__ raises RuntimeError before ever touching
    Redis."""
    worker = create_worker(WorkerSettings)

    assert "sync_asset_master_task" in worker.functions
    assert "collect_prices_task" in worker.functions


def test_cron_jobs_registered_with_integer_weekday_set() -> None:
    """arq's weekday matcher only accepts int/set[int] (or a single string
    Literal), never a set of weekday-name strings — a string set silently
    never matches and crashes worker boot with OverflowError instead."""
    cron_jobs = WorkerSettings.cron_jobs
    assert cron_jobs is not None
    assert len(cron_jobs) == 2

    by_coroutine = {job.coroutine: job for job in cron_jobs}
    assert set(by_coroutine) == {sync_asset_master_task, collect_prices_task}

    for job in cron_jobs:
        assert job.weekday == {0, 1, 2, 3, 4}
        assert job.unique is True

    asset_master_job = by_coroutine[sync_asset_master_task]
    assert (asset_master_job.hour, asset_master_job.minute) == (7, 20)

    collect_prices_job = by_coroutine[collect_prices_task]
    assert (collect_prices_job.hour, collect_prices_job.minute) == (7, 30)


def test_on_startup_wires_fake_adapters_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DATA_SOURCE", raising=False)
    monkeypatch.delenv("DART_API_KEY", raising=False)
    ctx: dict[str, Any] = {}

    asyncio.run(build_data_sources_on_startup(ctx))

    assert isinstance(ctx["data_source"], FakeDataSource)
    assert isinstance(ctx["price_data_source"], FakePriceDataSource)
    assert isinstance(ctx["index_price_data_source"], FakeIndexPriceDataSource)
    assert isinstance(ctx["financial_statement_data_source"], FakeFinancialStatementDataSource)


def test_on_startup_wires_pykrx_adapters_when_data_source_is_krx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATA_SOURCE", "krx")
    monkeypatch.setenv("DART_API_KEY", "test-dart-key")
    ctx: dict[str, Any] = {}

    asyncio.run(build_data_sources_on_startup(ctx))

    assert isinstance(ctx["data_source"], PykrxDataSource)
    assert isinstance(ctx["price_data_source"], PykrxPriceDataSource)
    assert isinstance(ctx["index_price_data_source"], PykrxIndexPriceDataSource)
    assert isinstance(ctx["financial_statement_data_source"], DartFinancialStatementDataSource)


def test_on_startup_fails_closed_when_krx_selected_without_dart_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATA_SOURCE", "krx")
    monkeypatch.delenv("DART_API_KEY", raising=False)
    ctx: dict[str, Any] = {}

    with pytest.raises(RuntimeError):
        asyncio.run(build_data_sources_on_startup(ctx))


@pytest.mark.parametrize(
    ("redis_url", "expected_host", "expected_port", "expected_database"),
    [
        ("redis://localhost:6379/0", "localhost", 6379, 0),
        ("redis://redis:6379/0", "redis", 6379, 0),
        ("redis://localhost:6380/3", "localhost", 6380, 3),
    ],
)
def test_build_redis_settings_parses_dsn(
    redis_url: str, expected_host: str, expected_port: int, expected_database: int
) -> None:
    settings = build_redis_settings(redis_url)

    assert settings.host == expected_host
    assert settings.port == expected_port
    assert settings.database == expected_database
