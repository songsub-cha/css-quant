"""create market_prices table

Fourth real schema revision (SoT C3) — chains after 5e8dcb0561bf (assets).
No enum columns here, so unlike the ``assets`` revision this one needs
none of SoT B5.2/B5.3's idempotent enum handling.

Identity is ``(asset_id, date)`` — a composite primary key rather than a
surrogate ``id`` — one row per asset per trading day, enforced by
``ForeignKeyConstraint`` back to ``assets.id``.

Revision ID: 56083c1c2a22
Revises: 5e8dcb0561bf
Create Date: 2026-07-29 02:02:56.453341

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "56083c1c2a22"
down_revision: str | Sequence[str] | None = "5e8dcb0561bf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "market_prices",
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(20, 4), nullable=False),
        sa.Column("high", sa.Numeric(20, 4), nullable=False),
        sa.Column("low", sa.Numeric(20, 4), nullable=False),
        sa.Column("close", sa.Numeric(20, 4), nullable=False),
        sa.Column("adjusted_close", sa.Numeric(20, 4), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("trading_value", sa.Numeric(20, 4), nullable=False),
        sa.Column("market_cap", sa.Numeric(24, 2), nullable=True),
        sa.Column("halted", sa.Boolean(), nullable=False, server_default=sa.false()),
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
        sa.PrimaryKeyConstraint("asset_id", "date"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"]),
    )


def downgrade() -> None:
    op.drop_table("market_prices")
