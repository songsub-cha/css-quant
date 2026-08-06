from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.config import Settings


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("postgres://user:pw@localhost:5432/db", "postgresql+psycopg://user:pw@localhost:5432/db"),
        (
            "postgresql://user:pw@localhost:5432/db",
            "postgresql+psycopg://user:pw@localhost:5432/db",
        ),
        (
            "postgresql+asyncpg://user:pw@localhost:5432/db",
            "postgresql+psycopg://user:pw@localhost:5432/db",
        ),
        (
            "postgresql+psycopg2://user:pw@localhost:5432/db",
            "postgresql+psycopg://user:pw@localhost:5432/db",
        ),
        (
            "postgresql+psycopg://user:pw@localhost:5432/db",
            "postgresql+psycopg://user:pw@localhost:5432/db",
        ),
    ],
)
def test_database_url_normalizes_to_psycopg3(raw: str, expected: str) -> None:
    # secret_key intentionally omitted: sourced from conftest's
    # SECRET_KEY env default, same pattern as the other direct
    # Settings(...) constructions below that don't concern secret_key.
    settings = Settings(database_url=raw, cookie_secure=False)  # type: ignore[call-arg]

    assert settings.database_url == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("true", True),
        ("false", False),
    ],
)
def test_cookie_secure_parses_bool_strings(
    raw: str, expected: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Exercises the real BaseSettings env-var path (string -> bool coercion),
    # not just direct construction — this is how COOKIE_SECURE is actually
    # set in dev/prod compose env_file.
    monkeypatch.setenv("COOKIE_SECURE", raw)

    settings = Settings(_env_file=None)  # type: ignore[call-arg]  # loaded from env, see api/deps.py

    assert settings.cookie_secure is expected


def test_cookie_secure_has_no_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # SoT D2: COOKIE_SECURE must be set explicitly per deployment — unlike
    # database_url/redis_url, there is no fallback value to silently pick.
    # _env_file=None isolates this from a local apps/api/.env (e.g. via
    # `cp .env.example .env` per README) so the test proves the field is
    # required from the environment, not just absent from a given .env.
    monkeypatch.delenv("COOKIE_SECURE", raising=False)

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # type: ignore[call-arg]  # deliberately omitted to prove it's required


def test_signup_enabled_defaults_false() -> None:
    settings = Settings(cookie_secure=False)  # type: ignore[call-arg]  # secret_key from env, see above

    assert settings.signup_enabled is False


def test_secret_key_has_no_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # Same rationale as test_cookie_secure_has_no_default: SECRET_KEY must be
    # set explicitly per deployment, isolated from any local apps/api/.env.
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(ValidationError):
        Settings(cookie_secure=False, _env_file=None)  # type: ignore[call-arg]


def test_data_source_defaults_to_fake() -> None:
    settings = Settings(cookie_secure=False)  # type: ignore[call-arg]  # secret_key from env, see above

    assert settings.data_source == "fake"


def test_data_source_accepts_krx(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_SOURCE", "krx")

    settings = Settings(cookie_secure=False, _env_file=None)  # type: ignore[call-arg]

    assert settings.data_source == "krx"


def test_data_source_rejects_unknown_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_SOURCE", "bogus")

    with pytest.raises(ValidationError):
        Settings(cookie_secure=False, _env_file=None)  # type: ignore[call-arg]


def test_dart_api_key_defaults_to_none() -> None:
    settings = Settings(cookie_secure=False)  # type: ignore[call-arg]  # secret_key from env, see above

    assert settings.dart_api_key is None


def test_dart_api_key_accepts_explicit_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DART_API_KEY", "some-dart-key")

    settings = Settings(cookie_secure=False, _env_file=None)  # type: ignore[call-arg]

    assert settings.dart_api_key == "some-dart-key"


def test_secret_key_rejects_empty_string(monkeypatch: pytest.MonkeyPatch) -> None:
    # The bug this guards against: `cookie_secure: bool` fails closed on an
    # empty COOKIE_SECURE= value because pydantic can't coerce "" to bool,
    # but `secret_key: str` would accept "" as a valid string with no
    # min_length floor — exactly what a bare `SECRET_KEY=` line in
    # .env.example produces after `cp .env.example .env`. min_length=32
    # makes the empty string fail closed the same way.
    monkeypatch.setenv("SECRET_KEY", "")

    with pytest.raises(ValidationError):
        Settings(cookie_secure=False, _env_file=None)  # type: ignore[call-arg]


def test_universe_market_cap_min_defaults_to_300_billion() -> None:
    settings = Settings(cookie_secure=False)  # type: ignore[call-arg]  # secret_key from env, see above

    assert settings.universe_market_cap_min == Decimal("300000000000")


def test_universe_avg_trading_value_min_defaults_to_1_billion() -> None:
    settings = Settings(cookie_secure=False)  # type: ignore[call-arg]  # secret_key from env, see above

    assert settings.universe_avg_trading_value_min == Decimal("1000000000")


def test_universe_min_listed_days_defaults_to_60() -> None:
    settings = Settings(cookie_secure=False)  # type: ignore[call-arg]  # secret_key from env, see above

    assert settings.universe_min_listed_days == 60


def test_universe_thresholds_accept_env_var_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIVERSE_MARKET_CAP_MIN", "500000000000")
    monkeypatch.setenv("UNIVERSE_AVG_TRADING_VALUE_MIN", "2000000000")
    monkeypatch.setenv("UNIVERSE_MIN_LISTED_DAYS", "90")

    settings = Settings(cookie_secure=False, _env_file=None)  # type: ignore[call-arg]

    assert settings.universe_market_cap_min == Decimal("500000000000")
    assert settings.universe_avg_trading_value_min == Decimal("2000000000")
    assert settings.universe_min_listed_days == 90
