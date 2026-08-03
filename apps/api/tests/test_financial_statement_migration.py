"""Integration test for the ``financial_statements`` table migration (SoT C1/A6.1/A6.7.2).

Mirrors ``test_index_price_migration.py``: spins up a real Postgres container
via ``testcontainers`` and runs the actual Alembic migration chain against
it — not ``Base.metadata.create_all()``, which would not exercise the
hand-written composite primary key / idempotent enum creation / FK the way
the real migration does (SoT B5.2/B5.3 — see the "create_all vacuous
partial-index" precedent this repo has already hit once).

Docker is unavailable in this environment and in the css-executor worktree
(``tests/conftest.py`` — "no DB container in this environment"), so the
module-scoped ``postgres_url`` fixture below catches whatever exception
``testcontainers`` raises while reaching the Docker daemon and skips the
whole module. Only Docker-equipped CI actually exercises the assertions here.
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
        pytest.skip(f"Docker unavailable — skipping financial statement migration test ({exc})")
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


def test_migration_creates_financial_statements_table_with_expected_columns(
    engine: Engine,
) -> None:
    columns = {c["name"] for c in sa.inspect(engine).get_columns("financial_statements")}

    assert columns == {
        "asset_id",
        "fiscal_year",
        "fiscal_quarter",
        "consolidated_type",
        "revenue",
        "operating_income",
        "net_income",
        "total_assets",
        "total_liabilities",
        "total_equity",
        "disclosed_at",
        "rcept_no",
        "created_at",
        "updated_at",
    }


def test_financial_statements_primary_key_is_asset_fiscal_year_and_quarter(engine: Engine) -> None:
    pk = sa.inspect(engine).get_pk_constraint("financial_statements")

    assert set(pk["constrained_columns"]) == {"asset_id", "fiscal_year", "fiscal_quarter"}


def test_financial_statements_has_fk_to_assets(engine: Engine) -> None:
    fks = sa.inspect(engine).get_foreign_keys("financial_statements")

    assert len(fks) == 1
    assert fks[0]["referred_table"] == "assets"
    assert fks[0]["constrained_columns"] == ["asset_id"]


def test_insert_against_nonexistent_asset_violates_fk(engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    """
                    INSERT INTO financial_statements
                        (asset_id, fiscal_year, fiscal_quarter, consolidated_type,
                         disclosed_at, rcept_no)
                    VALUES
                        (:asset_id, :fiscal_year, :fiscal_quarter, :consolidated_type,
                         :disclosed_at, :rcept_no)
                    """
                ),
                {
                    "asset_id": generate_uuid7(),
                    "fiscal_year": 2025,
                    "fiscal_quarter": "ANNUAL",
                    "consolidated_type": "CFS",
                    "disclosed_at": "2026-03-31",
                    "rcept_no": "20260331000001",
                },
            )


def test_rcept_no_unique_constraint_rejects_duplicate(engine: Engine) -> None:
    with engine.begin() as conn:
        asset_id = _insert_asset(conn, ticker="017670")
        conn.execute(
            sa.text(
                """
                INSERT INTO financial_statements
                    (asset_id, fiscal_year, fiscal_quarter, consolidated_type,
                     disclosed_at, rcept_no)
                VALUES
                    (:asset_id, 2024, 'ANNUAL', 'CFS', '2025-03-31', 'DUPRCEPT0001')
                """
            ),
            {"asset_id": asset_id},
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            asset_id_2 = _insert_asset(conn, ticker="005490")
            conn.execute(
                sa.text(
                    """
                    INSERT INTO financial_statements
                        (asset_id, fiscal_year, fiscal_quarter, consolidated_type,
                         disclosed_at, rcept_no)
                    VALUES
                        (:asset_id, 2024, 'ANNUAL', 'CFS', '2025-03-31', 'DUPRCEPT0001')
                    """
                ),
                {"asset_id": asset_id_2},
            )


def test_enum_columns_round_trip(engine: Engine) -> None:
    with engine.begin() as conn:
        asset_id = _insert_asset(conn, ticker="105560")
        for fiscal_quarter in ("Q1", "H1", "Q3", "ANNUAL"):
            conn.execute(
                sa.text(
                    """
                    INSERT INTO financial_statements
                        (asset_id, fiscal_year, fiscal_quarter, consolidated_type,
                         disclosed_at, rcept_no)
                    VALUES
                        (:asset_id, 2025, :fiscal_quarter, 'OFS', '2026-05-15', :rcept_no)
                    """
                ),
                {
                    "asset_id": asset_id,
                    "fiscal_quarter": fiscal_quarter,
                    "rcept_no": f"ENUMRT{fiscal_quarter}",
                },
            )
        rows = conn.execute(
            sa.text(
                "SELECT fiscal_quarter FROM financial_statements WHERE asset_id = :asset_id"
            ),
            {"asset_id": asset_id},
        ).all()

    assert {row.fiscal_quarter for row in rows} == {"Q1", "H1", "Q3", "ANNUAL"}


def test_alembic_downgrade_removes_financial_statements_table_and_enum_types(
    migrated_database_url: str,
) -> None:
    """Downgrades then re-upgrades so later-collected tests keep a valid schema.

    Targets the explicit predecessor revision (``bfb3e5e201c3``, the
    index_prices revision) rather than a relative ``downgrade -1`` — same
    rationale as ``test_index_price_migration.py``: a relative ``-1`` only
    targets whatever is directly below the current head, so it silently
    starts undoing the wrong revision the moment another issue chains a new
    head above this one.
    """
    _run_alembic(migrated_database_url, "downgrade", "bfb3e5e201c3")

    engine = create_engine(migrated_database_url)
    try:
        assert not sa.inspect(engine).has_table("financial_statements")
        with engine.connect() as conn:
            for enum_name in ("fiscal_quarter", "consolidated_type"):
                enum_exists = conn.execute(
                    sa.text("SELECT 1 FROM pg_type WHERE typname = :name"), {"name": enum_name}
                ).first()
                assert enum_exists is None
    finally:
        engine.dispose()

    _run_alembic(migrated_database_url, "upgrade", "head")
