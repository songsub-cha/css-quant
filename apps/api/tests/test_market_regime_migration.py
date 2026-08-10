"""Integration test for the ``market_regimes`` table migration (SoT A6.2/A6.3/C3).

Mirrors ``test_index_price_migration.py``: spins up a real Postgres
container via ``testcontainers`` and runs the actual Alembic migration chain
against it — not ``Base.metadata.create_all()``, which would not exercise
the hand-written primary key / idempotent enum creation the way the real
migration does.

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
        pytest.skip(f"Docker unavailable — skipping market regime migration test ({exc})")
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


def test_migration_creates_market_regimes_table_with_expected_columns(engine: Engine) -> None:
    columns = {c["name"] for c in sa.inspect(engine).get_columns("market_regimes")}

    assert columns == {
        "regime_date",
        "regime",
        "kospi_close",
        "kospi_ma200",
        "vkospi",
        "kospi_volatility_20d",
        "market_shock",
        "signals",
        "created_at",
        "updated_at",
    }


def test_market_regimes_primary_key_is_regime_date(engine: Engine) -> None:
    pk = sa.inspect(engine).get_pk_constraint("market_regimes")

    assert set(pk["constrained_columns"]) == {"regime_date"}


def test_market_regimes_table_has_no_foreign_keys(engine: Engine) -> None:
    """No ``assets`` FK — a regime is a market-wide judgement, not per-instrument."""
    fks = sa.inspect(engine).get_foreign_keys("market_regimes")

    assert fks == []


def test_regime_status_enum_round_trips_both_values(engine: Engine) -> None:
    with engine.begin() as conn:
        for i, regime in enumerate(("NORMAL", "DEFENSIVE")):
            conn.execute(
                sa.text(
                    """
                    INSERT INTO market_regimes
                        (regime_date, regime, kospi_close, kospi_ma200, vkospi,
                         kospi_volatility_20d, market_shock, signals)
                    VALUES
                        (:regime_date, :regime, 2665, 2600, 15, 0.01, false, '{}')
                    """
                ),
                {"regime_date": f"2026-07-{29 + i}", "regime": regime},
            )
        rows = conn.execute(sa.text("SELECT regime FROM market_regimes")).all()

    assert {row.regime for row in rows} == {"NORMAL", "DEFENSIVE"}


def test_vkospi_is_nullable(engine: Engine) -> None:
    columns = {c["name"]: c for c in sa.inspect(engine).get_columns("market_regimes")}

    assert columns["vkospi"]["nullable"] is True
    assert columns["kospi_volatility_20d"]["nullable"] is False


def test_alembic_downgrade_removes_market_regimes_table_and_enum_type(
    migrated_database_url: str,
) -> None:
    """Downgrades then re-upgrades so later-collected tests keep a valid schema.

    Targets the explicit predecessor revision (``d2a6f83e1c47``, the
    financial_statements revision) rather than a relative ``downgrade -1`` —
    same rationale as ``test_index_price_migration.py``: a relative ``-1``
    only targets whatever is directly below the current head, so it
    silently starts undoing the wrong revision the moment another issue
    chains a new head above this one.
    """
    _run_alembic(migrated_database_url, "downgrade", "d2a6f83e1c47")

    engine = create_engine(migrated_database_url)
    try:
        assert not sa.inspect(engine).has_table("market_regimes")
        with engine.connect() as conn:
            enum_exists = conn.execute(
                sa.text("SELECT 1 FROM pg_type WHERE typname = 'regime_status'")
            ).first()
        assert enum_exists is None
    finally:
        engine.dispose()

    _run_alembic(migrated_database_url, "upgrade", "head")
