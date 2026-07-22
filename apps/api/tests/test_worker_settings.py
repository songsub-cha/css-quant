import pytest
from arq.worker import create_worker

from src.workers.settings import WorkerSettings, build_redis_settings


def test_worker_settings_boots_without_redis() -> None:
    """WorkerSettings must carry at least one function/cron_job or
    arq.worker.Worker.__init__ raises RuntimeError before ever touching
    Redis (functions=[] previously crashed the worker on boot)."""
    worker = create_worker(WorkerSettings)

    assert "healthcheck" in worker.functions


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
