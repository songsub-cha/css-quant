"""create asset_factors table

Ninth real schema revision (SoT A6.1 stage 2/C3) — chains after
4c6521709c67 (market_regimes). No new enum — every column is a primitive
(``Numeric``/``Boolean``/``Date``).

FK to ``assets.id`` (like ``financial_statements``, unlike
``market_regimes``/``index_prices``) — a factor snapshot always belongs to a
listed instrument. Identity is ``(asset_id, factor_date)``, a composite
primary key rather than a surrogate ``id`` — one row per included universe
asset per trading day (see ``src/domain/asset_factor.py``).

Column precision: momentum/quality-ratio columns use ``Numeric(10, 6)``
(matching ``market_regimes.kospi_volatility_20d``'s scale for small ratio
values); ``per``/``pbr`` use ``Numeric(14, 4)`` (multiples can run into the
thousands for near-zero-earnings names); ``avg_trading_value_20d`` matches
``market_prices.trading_value``'s ``Numeric(20, 4)``; ``market_cap`` matches
``market_prices.market_cap``'s ``Numeric(24, 2)``.

Revision ID: 149af6067e5f
Revises: 4c6521709c67
Create Date: 2026-08-07 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "149af6067e5f"
down_revision: str | Sequence[str] | None = "4c6521709c67"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RATIO_PRECISION = sa.Numeric(10, 6)
_MULTIPLE_PRECISION = sa.Numeric(14, 4)


def upgrade() -> None:
    op.create_table(
        "asset_factors",
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("factor_date", sa.Date(), nullable=False),
        sa.Column("momentum_3m", _RATIO_PRECISION, nullable=True),
        sa.Column("momentum_6m", _RATIO_PRECISION, nullable=True),
        sa.Column("dist_52w_high", _RATIO_PRECISION, nullable=True),
        sa.Column("ma20_deviation", _RATIO_PRECISION, nullable=True),
        sa.Column("roe", _RATIO_PRECISION, nullable=True),
        sa.Column("op_margin", _RATIO_PRECISION, nullable=True),
        sa.Column("revenue_growth_yoy", _RATIO_PRECISION, nullable=True),
        sa.Column("debt_ratio", _RATIO_PRECISION, nullable=True),
        sa.Column("per", _MULTIPLE_PRECISION, nullable=True),
        sa.Column("pbr", _MULTIPLE_PRECISION, nullable=True),
        sa.Column("avg_trading_value_20d", sa.Numeric(20, 4), nullable=True),
        sa.Column("volume_cv", _RATIO_PRECISION, nullable=True),
        sa.Column("volatility_60d", _RATIO_PRECISION, nullable=True),
        sa.Column("mdd_60d", _RATIO_PRECISION, nullable=True),
        sa.Column("gap_frequency_60d", _RATIO_PRECISION, nullable=True),
        sa.Column("market_cap", sa.Numeric(24, 2), nullable=True),
        sa.Column("is_managed", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_alert", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("financial_data_as_of", sa.Date(), nullable=True),
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
        sa.PrimaryKeyConstraint("asset_id", "factor_date"),
    )


def downgrade() -> None:
    op.drop_table("asset_factors")
