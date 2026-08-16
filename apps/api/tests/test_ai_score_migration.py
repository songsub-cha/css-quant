"""Integration test for the ``ai_scores`` table migration (SoT A6.1/C3).

Spins up a real Postgres container via ``testcontainers`` and runs the
actual Alembic migration chain against it — not ``Base.metadata.create_all()``
(SoT B5.2/B5.3 — the "create_all vacuous partial-index" precedent this repo
has already hit once). Same rationale as ``test_asset_factor_migration.py``.

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
        pytest.skip(f"Docker unavailable — skipping ai score migration test ({exc})")
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


_MINIMAL_SCORE_ROW = {
    "regime": "NORMAL",
    "total_score": "65.50",
    "momentum_score": "70.00",
    "quality_score": "60.00",
    "value_score": "55.00",
    "liquidity_score": "80.00",
    "risk_score": "50.00",
}


def _insert_score(conn: sa.Connection, *, asset_id: str, score_date: str) -> None:
    conn.execute(
        sa.text(
            """
            INSERT INTO ai_scores
                (asset_id, score_date, regime, total_score, momentum_score,
                 quality_score, value_score, liquidity_score, risk_score)
            VALUES
                (:asset_id, :score_date, :regime, :total_score, :momentum_score,
                 :quality_score, :value_score, :liquidity_score, :risk_score)
            """
        ),
        {"asset_id": asset_id, "score_date": score_date, **_MINIMAL_SCORE_ROW},
    )


def test_migration_creates_ai_scores_table_with_expected_columns(engine: Engine) -> None:
    columns = {c["name"] for c in sa.inspect(engine).get_columns("ai_scores")}

    assert columns == {
        "asset_id",
        "score_date",
        "regime",
        "total_score",
        "momentum_score",
        "quality_score",
        "value_score",
        "liquidity_score",
        "risk_score",
        "summary",
        "positive_reasons",
        "risk_reasons",
        "llm_model",
        "llm_generated_at",
        "created_at",
        "updated_at",
    }


def test_ai_scores_primary_key_is_asset_id_and_score_date(engine: Engine) -> None:
    pk = sa.inspect(engine).get_pk_constraint("ai_scores")

    assert set(pk["constrained_columns"]) == {"asset_id", "score_date"}


def test_ai_scores_has_fk_to_assets(engine: Engine) -> None:
    fks = sa.inspect(engine).get_foreign_keys("ai_scores")

    assert len(fks) == 1
    assert fks[0]["referred_table"] == "assets"
    assert fks[0]["constrained_columns"] == ["asset_id"]


def test_insert_against_nonexistent_asset_violates_fk(engine: Engine) -> None:
    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            _insert_score(conn, asset_id=str(generate_uuid7()), score_date="2026-08-16")


def test_insert_with_null_llm_fields_succeeds(engine: Engine) -> None:
    """LLM-authored fields are all nullable — this pipeline (stage 5 out of
    scope, issue #62) always leaves them NULL."""
    with engine.begin() as conn:
        asset_id = _insert_asset(conn, ticker="017670")
        _insert_score(conn, asset_id=asset_id, score_date="2026-08-16")
        row = conn.execute(
            sa.text(
                "SELECT summary, positive_reasons, risk_reasons, llm_model, llm_generated_at"
                " FROM ai_scores WHERE asset_id = :asset_id"
            ),
            {"asset_id": asset_id},
        ).one()

    assert row.summary is None
    assert row.positive_reasons is None
    assert row.risk_reasons is None
    assert row.llm_model is None
    assert row.llm_generated_at is None


def test_insert_with_invalid_regime_value_violates_enum(engine: Engine) -> None:
    with pytest.raises(DataError):
        with engine.begin() as conn:
            asset_id = _insert_asset(conn, ticker="105560")
            conn.execute(
                sa.text(
                    """
                    INSERT INTO ai_scores
                        (asset_id, score_date, regime, total_score, momentum_score,
                         quality_score, value_score, liquidity_score, risk_score)
                    VALUES
                        (:asset_id, :score_date, 'BOGUS', 65.5, 70, 60, 55, 80, 50)
                    """
                ),
                {"asset_id": asset_id, "score_date": "2026-08-16"},
            )


def test_duplicate_asset_id_and_score_date_violates_pk(engine: Engine) -> None:
    with engine.begin() as conn:
        asset_id = _insert_asset(conn, ticker="000660")
        _insert_score(conn, asset_id=asset_id, score_date="2026-08-16")

    with pytest.raises(IntegrityError):
        with engine.begin() as conn:
            _insert_score(conn, asset_id=asset_id, score_date="2026-08-16")


def test_alembic_downgrade_removes_ai_scores_table_but_keeps_regime_status_enum(
    migrated_database_url: str,
) -> None:
    """Targets the explicit predecessor revision (``149af6067e5f``, the
    asset_factors revision) rather than a relative ``downgrade -1`` — same
    rationale as ``test_asset_factor_migration.py``. Also confirms the
    downgrade does NOT drop ``regime_status`` — ``market_regimes`` still owns
    and depends on that type.
    """
    _run_alembic(migrated_database_url, "downgrade", "149af6067e5f")

    engine = create_engine(migrated_database_url)
    try:
        inspector = sa.inspect(engine)
        assert not inspector.has_table("ai_scores")
        assert inspector.has_table("market_regimes")
        with engine.connect() as conn:
            enum_still_exists = conn.execute(
                sa.text("SELECT 1 FROM pg_type WHERE typname = 'regime_status'")
            ).scalar_one_or_none()
        assert enum_still_exists == 1
    finally:
        engine.dispose()

    _run_alembic(migrated_database_url, "upgrade", "head")
