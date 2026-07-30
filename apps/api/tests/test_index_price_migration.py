"""Integration test for the ``index_prices`` table migration (SoT A6.2/A6.3).

Mirrors ``test_job_run_migration.py``: spins up a real Postgres container via
``testcontainers`` and runs the actual Alembic migration chain against it —
not ``Base.metadata.create_all()``, which would not exercise the hand-written
composite primary key / idempotent enum creation the way the real migration
does.

Docker is unavailable in this environment and in the css-executor worktree
(``tests/conftest.py`` — "no DB container in this environment"), so the
module-scoped ``postgres_url`` fixture below catches whatever exception
``testcontainers`` raises while reaching the Docker daemon and skips the
whole module. Only Docker-equipped CI actually exercises the assertions
here.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine, create_engine
from testcontainers.community.postgres import PostgresContainer

_API_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def postgres_url() -> Generator[str, None, None]:
    try:
        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:  # noqa: BLE001 - Docker absence surfaces as varied exception types
        pytest.skip(f"Docker unavailable — skipping index price migration test ({exc})")
    try:
        yield container.get_connection_url()
    finally:
        container.stop()


def _run_alembic(database_url: str, *args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=_API_ROOT,
        env={**os.environ, "DATABASE_URL": database_url},
        check=True,
    )


@pytest.fixture(scope="module")
def migrated_database_url(postgres_url: str) -> str:
    _run_alembic(postgres_url, "upgrade", "head")
    return postgres_url


@pytest.fixture(scope="module")
def engine(migrated_database_url: str) -> Generator[Engine, None, None]:
    eng = create_engine(migrated_database_url)
    try:
        yield eng
    finally:
        eng.dispose()


def test_migration_creates_index_prices_table_with_expected_columns(engine: Engine) -> None:
    columns = {c["name"] for c in sa.inspect(engine).get_columns("index_prices")}

    assert columns == {
        "index_code",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "trading_value",
        "created_at",
        "updated_at",
    }


def test_index_prices_primary_key_is_index_code_and_date(engine: Engine) -> None:
    pk = sa.inspect(engine).get_pk_constraint("index_prices")

    assert set(pk["constrained_columns"]) == {"index_code", "date"}


def test_index_prices_table_has_no_foreign_keys(engine: Engine) -> None:
    """No ``assets`` FK — an index is not a tradable, listed instrument (SoT domain docstring)."""
    fks = sa.inspect(engine).get_foreign_keys("index_prices")

    assert fks == []


def test_index_code_enum_round_trips_both_values(engine: Engine) -> None:
    with engine.begin() as conn:
        for index_code in ("KOSPI", "VKOSPI"):
            conn.execute(
                sa.text(
                    """
                    INSERT INTO index_prices
                        (index_code, date, open, high, low, close, volume, trading_value)
                    VALUES
                        (:index_code, :date, 1, 1, 1, 1, 1, 1)
                    """
                ),
                {"index_code": index_code, "date": "2026-07-29"},
            )
        rows = conn.execute(
            sa.text("SELECT index_code FROM index_prices WHERE date = :date"),
            {"date": "2026-07-29"},
        ).all()

    assert {row.index_code for row in rows} == {"KOSPI", "VKOSPI"}


def test_alembic_downgrade_removes_index_prices_table_and_enum_type(
    migrated_database_url: str,
) -> None:
    """Downgrades then re-upgrades so later-collected tests keep a valid schema.

    Targets the explicit predecessor revision (``2b904345db6d``, the
    job_runs-timestamps revision) rather than a relative ``downgrade -1`` —
    same rationale as ``test_job_run_migration.py``: a relative ``-1`` only
    targets whatever is directly below the current head, so it silently
    starts undoing the wrong revision the moment another issue chains a new
    head above this one.
    """
    _run_alembic(migrated_database_url, "downgrade", "2b904345db6d")

    engine = create_engine(migrated_database_url)
    try:
        assert not sa.inspect(engine).has_table("index_prices")
        with engine.connect() as conn:
            enum_exists = conn.execute(
                sa.text("SELECT 1 FROM pg_type WHERE typname = 'index_code'")
            ).first()
        assert enum_exists is None
    finally:
        engine.dispose()

    _run_alembic(migrated_database_url, "upgrade", "head")
