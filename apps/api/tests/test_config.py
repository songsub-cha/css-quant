import pytest

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
    settings = Settings(database_url=raw)

    assert settings.database_url == expected
