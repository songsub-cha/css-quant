"""create ai_scores table

Tenth real schema revision (SoT A6.1 stages 3/4/6/C3) — chains after
149af6067e5f (asset_factors). No new enum: ``regime`` reuses the
``regime_status`` Postgres type ``market_regimes`` (4c6521709c67) already
owns via ``create_type=False`` — this revision neither creates nor drops
that type, since ``market_regimes`` still depends on it independently of
whether ``ai_scores`` exists.

FK to ``assets.id`` (like ``asset_factors``/``financial_statements``,
unlike ``market_regimes``) — a score row always belongs to a listed
instrument. Identity is ``(asset_id, score_date)``, a composite primary key
rather than a surrogate ``id`` — one row per scored (non-on-hold) asset per
trading day (see ``src/domain/ai_score.py``).

Column precision: the six score columns (``total``/``momentum``/``quality``/
``value``/``liquidity``/``risk_score``) are ``Numeric(5, 2)`` per SoT C3 —
0~100 with two decimal places. LLM-authored fields
(``summary``/``positive_reasons``/``risk_reasons``/``llm_model``/
``llm_generated_at``) are all nullable — SoT A6.1 stage 5 is out of scope
for this revision's writer (issue #62's plan); every row this revision's
caller inserts leaves them ``NULL``.

Revision ID: b8b6628e93d4
Revises: 149af6067e5f
Create Date: 2026-08-16 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8b6628e93d4"
down_revision: str | Sequence[str] | None = "149af6067e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REGIME_STATUS_ENUM = postgresql.ENUM(
    "NORMAL", "DEFENSIVE", name="regime_status", create_type=False
)
_SCORE_PRECISION = sa.Numeric(5, 2)


def upgrade() -> None:
    op.create_table(
        "ai_scores",
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("score_date", sa.Date(), nullable=False),
        sa.Column("regime", _REGIME_STATUS_ENUM, nullable=False),
        sa.Column("total_score", _SCORE_PRECISION, nullable=False),
        sa.Column("momentum_score", _SCORE_PRECISION, nullable=False),
        sa.Column("quality_score", _SCORE_PRECISION, nullable=False),
        sa.Column("value_score", _SCORE_PRECISION, nullable=False),
        sa.Column("liquidity_score", _SCORE_PRECISION, nullable=False),
        sa.Column("risk_score", _SCORE_PRECISION, nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("positive_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("risk_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("llm_model", sa.String(), nullable=True),
        sa.Column("llm_generated_at", sa.DateTime(timezone=True), nullable=True),
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
        sa.PrimaryKeyConstraint("asset_id", "score_date"),
    )


def downgrade() -> None:
    op.drop_table("ai_scores")
    # regime_status enum intentionally NOT dropped — market_regimes still owns it.
