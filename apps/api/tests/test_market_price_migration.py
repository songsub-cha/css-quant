"""Integration test for the ``market_prices`` table migration (SoT C3).

Mirrors ``test_asset_migration.py``: spins up a real Postgres container via
``testcontainers`` and runs the actual Alembic migration chain against it.

Docker is unavailable in this environment and in the css-executor worktree
(``tests/conftest.py`` — "no DB container in this environment"), so the
module-scoped ``postgres_url`` fixture below catches whatever exception
``testcontainers`` raises while reaching the Docker daemon and skips the
whole module. Only Docker-equipped CI (``ubuntu-latest``, no extra service
config needed) actually exercises the assertions here.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Generator
from pathlib import Path
from uuid import UUID

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
        pytest.skip(f"Docker unavailable — skipping market_price migration test ({exc})")
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


def _insert_asset(conn: sa.Connection, *, ticker: str) -> UUID:
    """Minimal valid ``assets`` row — ``market_prices`` FK requires one to exist."""
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
    return asset_id


def _insert_market_price(
    conn: sa.Connection, *, asset_id: UUID, price_date: str = "2026-07-29"
) -> None:
    conn.execute(
        sa.text(
            """
            INSERT INTO market_prices
                (asset_id, date, open, high, low, close,
                 adjusted_close, volume, trading_value)
            VALUES
                (:asset_id, :date, :open, :high, :low, :close,
                 :adjusted_close, :volume, :trading_value)
            """
        ),
        {
            "asset_id": asset_id,
            "date": price_date,
            "open": "71000.0000",
            "high": "71500.0000",
            "low": "70500.0000",
            "close": "71200.0000",
            "adjusted_close": "71200.0000",
            "volume": 15_000_000,
            "trading_value": "1068000000000.0000",
        },
    )


def test_migration_creates_market_prices_table_with_expected_columns(engine: Engine) -> None:
    columns = {c["name"] for c in sa.inspect(engine).get_columns("market_prices")}

    assert columns == {
        "asset_id",
        "date",
        "open",
        "high",
        "low",
        "close",
        "adjusted_close",
        "volume",
        "trading_value",
        "market_cap",
        "halted",
        "created_at",
        "updated_at",
    }


def test_insert_with_nonexistent_asset_id_violates_foreign_key(engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            _insert_market_price(conn, asset_id=generate_uuid7())


def test_duplicate_asset_id_and_date_violates_primary_key(engine: Engine) -> None:
    with engine.begin() as conn:
        asset_id = _insert_asset(conn, ticker="005930")
        _insert_market_price(conn, asset_id=asset_id)

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            _insert_market_price(conn, asset_id=asset_id)


def test_alembic_downgrade_removes_market_prices_table(migrated_database_url: str) -> None:
    """Downgrades then re-upgrades so later-collected tests keep a valid schema.

    Self-contained rather than relying on running last in file-declaration
    order: it restores head afterward regardless of test collection order.

    Targets the explicit predecessor revision (``5e8dcb0561bf``, the assets
    revision) rather than a relative ``downgrade -1``: a relative ``-1``
    only targets whatever is directly below the current head, so it would
    silently start undoing the wrong revision the moment another issue
    chains a new head above ``market_prices`` — the same regression this
    issue just fixed in ``test_asset_migration.py``'s sibling test. An
    explicit target stays correct however many revisions get added above
    ``market_prices``.
    """
    _run_alembic(migrated_database_url, "downgrade", "5e8dcb0561bf")

    engine = create_engine(migrated_database_url)
    try:
        assert not sa.inspect(engine).has_table("market_prices")
    finally:
        engine.dispose()

    _run_alembic(migrated_database_url, "upgrade", "head")
