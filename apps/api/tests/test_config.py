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
