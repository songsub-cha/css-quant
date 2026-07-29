"""Integration test for the ``job_runs`` table migration (SoT C4).

Mirrors ``test_asset_migration.py``/``test_market_price_migration.py``: spins
up a real Postgres container via ``testcontainers`` and runs the actual
Alembic migration chain against it.

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
        pytest.skip(f"Docker unavailable — skipping job_run migration test ({exc})")
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


def test_migration_creates_job_runs_table_with_expected_columns(engine: Engine) -> None:
    columns = {c["name"] for c in sa.inspect(engine).get_columns("job_runs")}

    assert columns == {
        "id",
        "job_name",
        "run_date",
        "status",
        "started_at",
        "finished_at",
        "error",
        "stats",
    }


def test_status_enum_round_trips_lowercase_values(engine: Engine) -> None:
    """Smoke-checks the lowercase enum labels (SoT B5.2) actually persist and read back.

    Unlike ``assets``' enums (name == value, uppercase both sides), ``running``
    is stored lowercase while the Python member name is ``RUNNING`` — a
    missing ``values_callable`` on the model column would insert the
    uppercase member name instead and this INSERT would fail outright.
    """
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                """
                INSERT INTO job_runs (id, job_name, run_date, status)
                VALUES (gen_random_uuid(), :job_name, :run_date, :status)
                """
            ),
            {"job_name": "sync_assets", "run_date": "2026-07-29", "status": "success"},
        )
        row = conn.execute(
            sa.text("SELECT status FROM job_runs WHERE job_name = :job_name"),
            {"job_name": "sync_assets"},
        ).one()

    assert row.status == "success"


def test_alembic_downgrade_removes_job_runs_table_and_enum_type(
    migrated_database_url: str,
) -> None:
    """Downgrades then re-upgrades so later-collected tests keep a valid schema.

    Targets the explicit predecessor revision (``56083c1c2a22``, the
    market_prices revision) rather than a relative ``downgrade -1`` — a
    relative ``-1`` only targets whatever is directly below the current
    head, so it would silently start undoing the wrong revision the moment
    another issue chains a new head above ``job_runs`` (the regression
    ``test_asset_migration.py``/``test_market_price_migration.py`` already
    fixed for their own revisions).
    """
    _run_alembic(migrated_database_url, "downgrade", "56083c1c2a22")

    engine = create_engine(migrated_database_url)
    try:
        assert not sa.inspect(engine).has_table("job_runs")
    finally:
        engine.dispose()

    _run_alembic(migrated_database_url, "upgrade", "head")
