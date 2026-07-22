import pytest

from src.workers.settings import build_redis_settings


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
