"""Integration test for the ``watchlist_items`` table migration (SoT A5.2/C3).

Spins up a real Postgres container via ``testcontainers`` and runs the
actual Alembic migration chain against it — not ``Base.metadata.create_all()``
(SoT B5.2/B5.3 — the "create_all vacuous partial-index" precedent this repo
has already hit once). Same rationale as ``test_ai_score_migration.py``.

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
from sqlalchemy.exc import DataError, IntegrityError
from testcontainers.community.postgres import PostgresContainer

from src.domain.ids import generate_uuid7

_API_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def postgres_url() -> Generator[str, None, None]:
    try:
        container = PostgresContainer("postgres:16-alpine", driver="psycopg")
        container.start()
    except Exception as exc:  # noqa: BLE001 - Docker absence surfaces as varied exception types
        pytest.skip(f"Docker unavailable — skipping watchlist migration test ({exc})")
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


def _insert_user(conn: sa.Connection, *, email: str) -> str:
    user_id = generate_uuid7()
    conn.execute(
        sa.text(
            "INSERT INTO users (id, email, password_hash) VALUES (:id, :email, :password_hash)"
        ),
        {"id": user_id, "email": email, "password_hash": "hashed"},
    )
    return str(user_id)


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


def _insert_watchlist_item(
    conn: sa.Connection, *, user_id: str, asset_id: str, kind: str = "watch"
) -> None:
    conn.execute(
        sa.text(
            """
            INSERT INTO watchlist_items (id, user_id, asset_id, kind)
            VALUES (:id, :user_id, :asset_id, :kind)
            """
        ),
        {"id": generate_uuid7(), "user_id": user_id, "asset_id": asset_id, "kind": kind},
    )


def test_migration_creates_watchlist_items_table_with_expected_columns(engine: Engine) -> None:
    columns = {c["name"] for c in sa.inspect(engine).get_columns("watchlist_items")}

    assert columns == {
        "id",
        "user_id",
        "asset_id",
        "kind",
        "note",
        "created_at",
        "updated_at",
    }


def test_watchlist_items_primary_key_is_id(engine: Engine) -> None:
    pk = sa.inspect(engine).get_pk_constraint("watchlist_items")

    assert pk["constrained_columns"] == ["id"]


def test_watchlist_items_has_fks_to_users_and_assets(engine: Engine) -> None:
    fks = sa.inspect(engine).get_foreign_keys("watchlist_items")
    fks_by_column = {fk["constrained_columns"][0]: fk["referred_table"] for fk in fks}

    assert fks_by_column == {"user_id": "users", "asset_id": "assets"}


def test_kind_enum_round_trips_lowercase_values(engine: Engine) -> None:
    """Smoke-checks the lowercase enum labels (SoT B5.2) actually persist and read back.

    A missing ``values_callable`` on the model column would insert the
    uppercase member name (``WATCH``) instead and this INSERT would fail
    outright — same regression ``test_job_run_migration.py`` guards.
    """
    with engine.begin() as conn:
        user_id = _insert_user(conn, email="watchlist-enum@example.com")
        asset_id = _insert_asset(conn, ticker="017670")
        _insert_watchlist_item(conn, user_id=user_id, asset_id=asset_id, kind="exclude")
        row = conn.execute(
            sa.text("SELECT kind FROM watchlist_items WHERE user_id = :user_id"),
            {"user_id": user_id},
        ).one()

    assert row.kind == "exclude"


def test_insert_with_invalid_kind_value_violates_enum(engine: Engine) -> None:
    with pytest.raises(DataError):
        with engine.begin() as conn:
            user_id = _insert_user(conn, email="watchlist-bad-enum@example.com")
            asset_id = _insert_asset(conn, ticker="105560")
            _insert_watchlist_item(conn, user_id=user_id, asset_id=asset_id, kind="BOGUS")


def test_insert_against_nonexistent_user_violates_fk(engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            asset_id = _insert_asset(conn, ticker="000660")
            _insert_watchlist_item(conn, user_id=str(generate_uuid7()), asset_id=asset_id)


def test_insert_against_nonexistent_asset_violates_fk(engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            user_id = _insert_user(conn, email="watchlist-no-asset@example.com")
            _insert_watchlist_item(conn, user_id=user_id, asset_id=str(generate_uuid7()))


def test_duplicate_user_id_and_asset_id_violates_unique_constraint(engine: Engine) -> None:
    with engine.begin() as conn:
        user_id = _insert_user(conn, email="watchlist-dup@example.com")
        asset_id = _insert_asset(conn, ticker="207940")
        _insert_watchlist_item(conn, user_id=user_id, asset_id=asset_id)

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            _insert_watchlist_item(conn, user_id=user_id, asset_id=asset_id, kind="exclude")


def test_alembic_downgrade_removes_watchlist_items_table_and_enum_type(
    migrated_database_url: str,
) -> None:
    """Targets the explicit predecessor revision (``b8b6628e93d4``, the
    ai_scores revision) rather than a relative ``downgrade -1`` — same
    rationale as ``test_ai_score_migration.py``.
    """
    _run_alembic(migrated_database_url, "downgrade", "b8b6628e93d4")

    engine = create_engine(migrated_database_url)
    try:
        inspector = sa.inspect(engine)
        assert not inspector.has_table("watchlist_items")
        with engine.connect() as conn:
            enum_still_exists = conn.execute(
                sa.text("SELECT 1 FROM pg_type WHERE typname = 'watchlist_kind'")
            ).scalar_one_or_none()
        assert enum_still_exists is None
    finally:
        engine.dispose()

    _run_alembic(migrated_database_url, "upgrade", "head")
