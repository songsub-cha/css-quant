"""create strategies table

Twelfth real schema revision (SoT A5.3/A6.5/C3) — chains after 033f04ddeb2f
(watchlist_items). Third *lowercase-valued* persisted enum pair after
``job_run_status`` and ``watchlist_kind`` (SoT B5.2/B5.3): the model's
``values_callable``, this migration's ``postgresql.ENUM`` labels, and the
idempotent ``DO $$ CREATE TYPE`` labels below all agree on lowercase for
both ``strategy_status`` and ``strategy_execution_mode``.

``config`` is jsonb (SoT A6.5's nested schema, validated at the Pydantic
boundary in ``src.domain.strategy_config`` rather than in the DB). ``version``
defaults to 1 and is bumped by the service layer on active-strategy config
edits (SoT A6.5 "활성 전략의 수정"). ``deleted_at`` implements SoT B4.10's
soft-delete requirement for strategies — no partial/unique index depends on
it, unlike ``assets.ticker`` (SoT C3), so a plain nullable column suffices.

FK to ``users.id`` only (no asset FK, unlike ``watchlist_items`` — a
strategy's asset universe is expressed inside ``config``, not a foreign key).

Revision ID: 1585ec96bc60
Revises: 033f04ddeb2f
Create Date: 2026-08-19 06:22:24.296632

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1585ec96bc60"
down_revision: str | Sequence[str] | None = "033f04ddeb2f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STRATEGY_STATUS_ENUM = postgresql.ENUM(
    "draft", "active", "paused", "archived", name="strategy_status", create_type=False
)
_STRATEGY_EXECUTION_MODE_ENUM = postgresql.ENUM(
    "backtest",
    "paper",
    "live_approval",
    "live_auto",
    name="strategy_execution_mode",
    create_type=False,
)


def _create_enum_type_idempotent(name: str, values: tuple[str, ...]) -> None:
    labels = ", ".join(f"'{value}'" for value in values)
    op.execute(
        f"""
        DO $$ BEGIN
            CREATE TYPE {name} AS ENUM ({labels});
        EXCEPTION
            WHEN duplicate_object THEN null;
        END $$;
        """
    )


def upgrade() -> None:
    _create_enum_type_idempotent("strategy_status", ("draft", "active", "paused", "archived"))
    _create_enum_type_idempotent(
        "strategy_execution_mode", ("backtest", "paper", "live_approval", "live_auto")
    )

    op.create_table(
        "strategies",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", _STRATEGY_STATUS_ENUM, nullable=False),
        sa.Column("execution_mode", _STRATEGY_EXECUTION_MODE_ENUM, nullable=False),
        sa.Column("config", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_strategies_user_id"),
    )


def downgrade() -> None:
    op.drop_table("strategies")
    op.execute("DROP TYPE IF EXISTS strategy_status")
    op.execute("DROP TYPE IF EXISTS strategy_execution_mode")
