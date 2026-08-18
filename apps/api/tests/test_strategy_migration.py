"""Integration test for the ``strategies`` table migration (SoT A5.3/A6.5/C3).

Same structure as ``test_watchlist_migration.py``: spins up a real Postgres
container via ``testcontainers`` and runs the actual Alembic migration
chain — not ``Base.metadata.create_all()`` (SoT B5.2/B5.3).

Docker is unavailable in this environment and in the css-executor worktree,
so the module-scoped ``postgres_url`` fixture below skips the whole module
when Docker can't be reached. Only Docker-equipped CI actually exercises
the assertions here.
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
        pytest.skip(f"Docker unavailable — skipping strategy migration test ({exc})")
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


def _insert_strategy(
    conn: sa.Connection,
    *,
    user_id: str,
    status: str = "draft",
    execution_mode: str = "backtest",
) -> None:
    conn.execute(
        sa.text(
            """
            INSERT INTO strategies (id, user_id, name, status, execution_mode, config, version)
            VALUES (:id, :user_id, :name, :status, :execution_mode, :config, :version)
            """
        ),
        {
            "id": generate_uuid7(),
            "user_id": user_id,
            "name": "Test Strategy",
            "status": status,
            "execution_mode": execution_mode,
            "config": "{}",
            "version": 1,
        },
    )


def test_migration_creates_strategies_table_with_expected_columns(engine: Engine) -> None:
    columns = {c["name"] for c in sa.inspect(engine).get_columns("strategies")}

    assert columns == {
        "id",
        "user_id",
        "name",
        "description",
        "status",
        "execution_mode",
        "config",
        "version",
        "deleted_at",
        "created_at",
        "updated_at",
    }


def test_strategies_primary_key_is_id(engine: Engine) -> None:
    pk = sa.inspect(engine).get_pk_constraint("strategies")

    assert pk["constrained_columns"] == ["id"]


def test_strategies_has_fk_to_users(engine: Engine) -> None:
    fks = sa.inspect(engine).get_foreign_keys("strategies")
    fks_by_column = {fk["constrained_columns"][0]: fk["referred_table"] for fk in fks}

    assert fks_by_column == {"user_id": "users"}


def test_status_and_execution_mode_enums_round_trip_lowercase_values(engine: Engine) -> None:
    """Smoke-checks the lowercase enum labels (SoT B5.2) round-trip correctly.

    A missing ``values_callable`` on the model column would insert the
    uppercase member name instead and this INSERT would fail outright —
    same regression ``test_watchlist_migration.py`` guards.
    """
    with engine.begin() as conn:
        user_id = _insert_user(conn, email="strategy-enum@example.com")
        _insert_strategy(conn, user_id=user_id, status="active", execution_mode="paper")
        row = conn.execute(
            sa.text("SELECT status, execution_mode FROM strategies WHERE user_id = :user_id"),
            {"user_id": user_id},
        ).one()

    assert row.status == "active"
    assert row.execution_mode == "paper"


def test_insert_with_invalid_status_value_violates_enum(engine: Engine) -> None:
    with pytest.raises(DataError):
        with engine.begin() as conn:
            user_id = _insert_user(conn, email="strategy-bad-status@example.com")
            _insert_strategy(conn, user_id=user_id, status="BOGUS")


def test_insert_with_invalid_execution_mode_value_violates_enum(engine: Engine) -> None:
    with pytest.raises(DataError):
        with engine.begin() as conn:
            user_id = _insert_user(conn, email="strategy-bad-mode@example.com")
            _insert_strategy(conn, user_id=user_id, execution_mode="BOGUS")


def test_insert_against_nonexistent_user_violates_fk(engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            _insert_strategy(conn, user_id=str(generate_uuid7()))


def test_version_defaults_to_1(engine: Engine) -> None:
    with engine.begin() as conn:
        user_id = _insert_user(conn, email="strategy-version-default@example.com")
        conn.execute(
            sa.text(
                """
                INSERT INTO strategies (id, user_id, name, status, execution_mode, config)
                VALUES (:id, :user_id, :name, :status, :execution_mode, :config)
                """
            ),
            {
                "id": generate_uuid7(),
                "user_id": user_id,
                "name": "No Explicit Version",
                "status": "draft",
                "execution_mode": "backtest",
                "config": "{}",
            },
        )
        row = conn.execute(
            sa.text("SELECT version FROM strategies WHERE user_id = :user_id"),
            {"user_id": user_id},
        ).one()

    assert row.version == 1


def test_alembic_downgrade_removes_strategies_table_and_enum_types(
    migrated_database_url: str,
) -> None:
    """Targets the explicit predecessor revision (``033f04ddeb2f``, the
    watchlist_items revision) rather than a relative ``downgrade -1`` — same
    rationale as ``test_watchlist_migration.py``.
    """
    _run_alembic(migrated_database_url, "downgrade", "033f04ddeb2f")

    engine = create_engine(migrated_database_url)
    try:
        inspector = sa.inspect(engine)
        assert not inspector.has_table("strategies")
        with engine.connect() as conn:
            status_enum_exists = conn.execute(
                sa.text("SELECT 1 FROM pg_type WHERE typname = 'strategy_status'")
            ).scalar_one_or_none()
            mode_enum_exists = conn.execute(
                sa.text("SELECT 1 FROM pg_type WHERE typname = 'strategy_execution_mode'")
            ).scalar_one_or_none()
        assert status_enum_exists is None
        assert mode_enum_exists is None
    finally:
        engine.dispose()

    _run_alembic(migrated_database_url, "upgrade", "head")
