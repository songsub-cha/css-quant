"""create market_regimes table

Eighth real schema revision (SoT A6.2/A6.3/C3) — chains after d2a6f83e1c47
(financial_statements). ``regime_status`` is uppercase-both-sides (matching
the Python ``RegimeStatus`` StrEnum member names, same as ``fiscal_quarter``/
``consolidated_type``) — no ``values_callable``/label mismatch risk, but the
idempotent ``DO $$ CREATE TYPE`` guard is applied for consistency with every
other enum-bearing revision in this chain.

No FK to ``assets`` (like ``index_prices``, unlike ``financial_statements``)
— a market regime is a market-wide judgement, not tied to a single listed
instrument. Identity is ``regime_date`` alone, not a composite key — exactly
one regime row per trading day (see ``src/domain/market_regime.py``'s module
docstring for why this differs from ``index_prices``' per-index key).

Revision ID: 4c6521709c67
Revises: d2a6f83e1c47
Create Date: 2026-08-04 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4c6521709c67"
down_revision: str | Sequence[str] | None = "d2a6f83e1c47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REGIME_STATUS_ENUM = postgresql.ENUM(
    "NORMAL", "DEFENSIVE", name="regime_status", create_type=False
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
    _create_enum_type_idempotent("regime_status", ("NORMAL", "DEFENSIVE"))

    op.create_table(
        "market_regimes",
        sa.Column("regime_date", sa.Date(), nullable=False),
        sa.Column("regime", _REGIME_STATUS_ENUM, nullable=False),
        sa.Column("kospi_close", sa.Numeric(20, 4), nullable=False),
        sa.Column("kospi_ma200", sa.Numeric(20, 4), nullable=False),
        sa.Column("vkospi", sa.Numeric(10, 4), nullable=True),
        sa.Column("kospi_volatility_20d", sa.Numeric(10, 6), nullable=False),
        sa.Column("market_shock", sa.Boolean(), nullable=False),
        sa.Column("signals", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        sa.PrimaryKeyConstraint("regime_date"),
    )


def downgrade() -> None:
    op.drop_table("market_regimes")
    op.execute("DROP TYPE IF EXISTS regime_status")
