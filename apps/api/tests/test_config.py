import pytest
from pydantic import ValidationError

from src.config import Settings


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("postgres://user:pw@localhost:5432/db", "postgresql+psycopg://user:pw@localhost:5432/db"),
        ("postgresql://user:pw@localhost:5432/db", "postgresql+psycopg://user:pw@localhost:5432/db"),
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
    settings = Settings(database_url=raw, cookie_secure=False)

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

    settings = Settings()  # type: ignore[call-arg]  # loaded from env, see api/deps.py

    assert settings.cookie_secure is expected


def test_cookie_secure_has_no_default(monkeypatch: pytest.MonkeyPatch) -> None:
    # SoT D2: COOKIE_SECURE must be set explicitly per deployment — unlike
    # database_url/redis_url, there is no fallback value to silently pick.
    monkeypatch.delenv("COOKIE_SECURE", raising=False)

    with pytest.raises(ValidationError):
        Settings()  # type: ignore[call-arg]  # deliberately omitted to prove it's required


def test_signup_enabled_defaults_false() -> None:
    settings = Settings(cookie_secure=False)

    assert settings.signup_enabled is False
