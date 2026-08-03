"""create index_prices table

Sixth real schema revision (SoT A6.2/A6.3) — chains after 2b904345db6d
(job_runs timestamps). ``index_code`` is an uppercase-both-sides enum
(``KOSPI``/``VKOSPI``, matching the Python member name), same shape as
``assets``' enums — unlike ``job_run_status``'s lowercase-valued enum, no
values_callable/label mismatch risk here (SoT B5.2/B5.3), but the idempotent
``DO $$ CREATE TYPE`` guard is still applied for consistency with every
other enum-bearing revision in this chain.

No FK to ``assets`` — an index is not a tradable, listed instrument (SoT
domain module docstring, ``src/domain/index_price.py``). Identity is
``(index_code, date)``, a composite primary key rather than a surrogate
``id`` — one row per index per trading day, mirroring ``market_prices``'
``(asset_id, date)`` shape.

Revision ID: bfb3e5e201c3
Revises: 2b904345db6d
Create Date: 2026-07-31 03:51:13.881599

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bfb3e5e201c3"
down_revision: str | Sequence[str] | None = "2b904345db6d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX_CODE_ENUM = postgresql.ENUM("KOSPI", "VKOSPI", name="index_code", create_type=False)


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
    _create_enum_type_idempotent("index_code", ("KOSPI", "VKOSPI"))

    op.create_table(
        "index_prices",
        sa.Column("index_code", _INDEX_CODE_ENUM, nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("open", sa.Numeric(20, 4), nullable=False),
        sa.Column("high", sa.Numeric(20, 4), nullable=False),
        sa.Column("low", sa.Numeric(20, 4), nullable=False),
        sa.Column("close", sa.Numeric(20, 4), nullable=False),
        sa.Column("volume", sa.BigInteger(), nullable=False),
        sa.Column("trading_value", sa.Numeric(20, 4), nullable=False),
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
        sa.PrimaryKeyConstraint("index_code", "date"),
    )


def downgrade() -> None:
    op.drop_table("index_prices")
    op.execute("DROP TYPE IF EXISTS index_code")
