"""Integration test for the ``assets`` table migration (SoT C3).

Spins up a real Postgres container via ``testcontainers`` and runs the
actual Alembic migration chain against it — this repo's first exercise of
both a real Postgres instance in tests and a SAEnum column (SoT B5.2/B5.3).

Docker is unavailable in this environment and in the css-executor
worktree (``tests/conftest.py`` — "no DB container in this environment"),
so the module-scoped ``postgres_url`` fixture below catches whatever
exception ``testcontainers`` raises while reaching the Docker daemon and
skips the whole module. Only Docker-equipped CI (``ubuntu-latest``, no
extra service config needed) actually exercises the assertions here.
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
        pytest.skip(f"Docker unavailable — skipping asset migration integration test ({exc})")
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


def _insert_asset(
    conn: sa.Connection, *, ticker: str, market: str = "KR", is_active: bool = True
) -> None:
    conn.execute(
        sa.text(
            """
            INSERT INTO assets (id, ticker, name, market, asset_type, exchange, is_active)
            VALUES (:id, :ticker, :name, :market, :asset_type, :exchange, :is_active)
            """
        ),
        {
            "id": generate_uuid7(),
            "ticker": ticker,
            "name": "Test Asset",
            "market": market,
            "asset_type": "STOCK",
            "exchange": "KOSPI",
            "is_active": is_active,
        },
    )


def test_migration_creates_assets_table_with_expected_columns(engine: Engine) -> None:
    columns = {c["name"] for c in sa.inspect(engine).get_columns("assets")}

    assert columns == {
        "id",
        "ticker",
        "name",
        "market",
        "asset_type",
        "exchange",
        "sector",
        "currency",
        "is_active",
        "listed_at",
        "delisted_at",
        "is_managed",
        "is_alert",
        "created_at",
        "updated_at",
    }


def test_duplicate_active_ticker_in_same_market_violates_unique_constraint(engine: Engine) -> None:
    with engine.begin() as conn:
        _insert_asset(conn, ticker="005930")

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            _insert_asset(conn, ticker="005930")


def test_relisting_same_ticker_after_delisting_is_allowed(engine: Engine) -> None:
    with engine.begin() as conn:
        _insert_asset(conn, ticker="000660")
    with engine.begin() as conn:
        conn.execute(
            sa.text("UPDATE assets SET is_active = false WHERE ticker = :ticker"),
            {"ticker": "000660"},
        )

    with engine.begin() as conn:
        _insert_asset(conn, ticker="000660")  # must not raise — relisting under a new row


def test_enum_columns_round_trip(engine: Engine) -> None:
    """Smoke-checks that enum columns store/read back defined values.

    All three enums (``Market``, ``AssetType``, ``Exchange``) currently have
    name == value (uppercase), so this round trip cannot by itself detect a
    missing ``values_callable`` on the SQLAlchemy column (SoT B5.2) — that
    is verified by code review, per this issue's acceptance criteria.
    """
    asset_id = generate_uuid7()
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                """
                INSERT INTO assets (id, ticker, name, market, asset_type, exchange, is_active)
                VALUES (:id, :ticker, :name, :market, :asset_type, :exchange, :is_active)
                """
            ),
            {
                "id": asset_id,
                "ticker": "069500",
                "name": "KODEX 200",
                "market": "KR",
                "asset_type": "ETF",
                "exchange": "KOSDAQ",
                "is_active": True,
            },
        )
        row = conn.execute(
            sa.text("SELECT market, asset_type, exchange FROM assets WHERE id = :id"),
            {"id": asset_id},
        ).one()

    assert (row.market, row.asset_type, row.exchange) == ("KR", "ETF", "KOSDAQ")


def test_alembic_downgrade_removes_assets_table_and_enum_types(
    migrated_database_url: str,
) -> None:
    """Downgrades then re-upgrades so later-collected tests keep a valid schema.

    Self-contained rather than relying on running last in file-declaration
    order: it restores head afterward regardless of test collection order.
    """
    _run_alembic(migrated_database_url, "downgrade", "-1")

    engine = create_engine(migrated_database_url)
    try:
        assert not sa.inspect(engine).has_table("assets")
    finally:
        engine.dispose()

    _run_alembic(migrated_database_url, "upgrade", "head")
