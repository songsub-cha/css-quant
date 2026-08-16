"""Integration test for the ``asset_factors`` table migration (SoT A6.1/C3).

Spins up a real Postgres container via ``testcontainers`` and runs the
actual Alembic migration chain against it — not ``Base.metadata.create_all()``,
which would not exercise the hand-written composite primary key / FK the way
the real migration does (SoT B5.2/B5.3 — see the "create_all vacuous
partial-index" precedent this repo has already hit once). Same rationale as
``test_financial_statement_migration.py``.

Docker is unavailable in this environment and in the css-executor worktree
(``tests/conftest.py`` — "no DB container in this environment"), so the
module-scoped ``postgres_url`` fixture below skips the whole module when
Docker can't be reached. Only Docker-equipped CI actually exercises the
assertions here.
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
from sqlalchemy.exc import IntegrityError
from testcontainers.community.postgres import PostgresContainer

from src.domain.ids import generate_uuid7

_API_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def postgres_url() -> Generator[str, None, None]:
    try:
        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:  # noqa: BLE001 - Docker absence surfaces as varied exception types
        pytest.skip(f"Docker unavailable — skipping asset factor migration test ({exc})")
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


def _insert_asset(conn: sa.Connection, *, ticker: str) -> str:
    asset_id = generate_uuid7()
    conn.execute(
        sa.text(
            """
            INSERT INTO assets (id, ticker, name, market, asset_type, exchange, is_active)
            VALUES (:id, :ticker, :name, :market, :asset_type, :exchange, :is_active)
            """
        ),
        {
            "id": asset_id,
            "ticker": ticker,
            "name": "Test Asset",
            "market": "KR",
            "asset_type": "STOCK",
            "exchange": "KOSPI",
            "is_active": True,
        },
    )
    return str(asset_id)


def test_migration_creates_asset_factors_table_with_expected_columns(engine: Engine) -> None:
    columns = {c["name"] for c in sa.inspect(engine).get_columns("asset_factors")}

    assert columns == {
        "asset_id",
        "factor_date",
        "momentum_3m",
        "momentum_6m",
        "dist_52w_high",
        "ma20_deviation",
        "roe",
        "op_margin",
        "revenue_growth_yoy",
        "debt_ratio",
        "per",
        "pbr",
        "avg_trading_value_20d",
        "volume_cv",
        "volatility_60d",
        "mdd_60d",
        "gap_frequency_60d",
        "market_cap",
        "is_managed",
        "is_alert",
        "financial_data_as_of",
        "created_at",
        "updated_at",
    }


def test_asset_factors_primary_key_is_asset_id_and_factor_date(engine: Engine) -> None:
    pk = sa.inspect(engine).get_pk_constraint("asset_factors")

    assert set(pk["constrained_columns"]) == {"asset_id", "factor_date"}


def test_asset_factors_has_fk_to_assets(engine: Engine) -> None:
    fks = sa.inspect(engine).get_foreign_keys("asset_factors")

    assert len(fks) == 1
    assert fks[0]["referred_table"] == "assets"
    assert fks[0]["constrained_columns"] == ["asset_id"]


def test_insert_against_nonexistent_asset_violates_fk(engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    """
                    INSERT INTO asset_factors (asset_id, factor_date)
                    VALUES (:asset_id, :factor_date)
                    """
                ),
                {"asset_id": generate_uuid7(), "factor_date": "2026-08-07"},
            )


def test_insert_with_all_null_factors_succeeds(engine: Engine) -> None:
    """Every factor column is nullable (SoT A6.7 신규상장 partial-history case) --
    only the composite PK and the FK are required."""
    with engine.begin() as conn:
        asset_id = _insert_asset(conn, ticker="017670")
        conn.execute(
            sa.text(
                "INSERT INTO asset_factors (asset_id, factor_date) VALUES (:asset_id, :factor_date)"
            ),
            {"asset_id": asset_id, "factor_date": "2026-08-07"},
        )
        row = conn.execute(
            sa.text("SELECT is_managed, is_alert FROM asset_factors WHERE asset_id = :asset_id"),
            {"asset_id": asset_id},
        ).one()

    assert row.is_managed is False
    assert row.is_alert is False


def test_duplicate_asset_id_and_factor_date_violates_pk(engine: Engine) -> None:
    with engine.begin() as conn:
        asset_id = _insert_asset(conn, ticker="105560")
        conn.execute(
            sa.text(
                "INSERT INTO asset_factors (asset_id, factor_date) VALUES (:asset_id, :factor_date)"
            ),
            {"asset_id": asset_id, "factor_date": "2026-08-07"},
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    "INSERT INTO asset_factors (asset_id, factor_date)"
                    " VALUES (:asset_id, :factor_date)"
                ),
                {"asset_id": asset_id, "factor_date": "2026-08-07"},
            )


def test_alembic_downgrade_removes_asset_factors_table(migrated_database_url: str) -> None:
    """Targets the explicit predecessor revision (``4c6521709c67``, the market_regimes
    revision) rather than a relative ``downgrade -1`` — same rationale as
    ``test_financial_statement_migration.py``: a relative ``-1`` only targets whatever
    is directly below the current head, so it silently starts undoing the wrong
    revision the moment another issue chains a new head above this one.
    """
    _run_alembic(migrated_database_url, "downgrade", "4c6521709c67")

    engine = create_engine(migrated_database_url)
    try:
        assert not sa.inspect(engine).has_table("asset_factors")
    finally:
        engine.dispose()

    _run_alembic(migrated_database_url, "upgrade", "head")
