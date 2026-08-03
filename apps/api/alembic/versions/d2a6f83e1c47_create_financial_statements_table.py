"""create financial_statements table

Seventh real schema revision (SoT C1/A6.1/A6.7.2) — chains after
bfb3e5e201c3 (index_prices). Both new enums (``fiscal_quarter``,
``consolidated_type``) are uppercase-both-sides (matching the Python member
name), same shape as ``assets``' enums — no values_callable/label mismatch
risk here (SoT B5.2/B5.3), but the idempotent ``DO $$ CREATE TYPE`` guard is
still applied for consistency with every other enum-bearing revision in this
chain.

FK to ``assets.id`` (unlike ``index_prices``) — a financial statement always
belongs to a listed company. Identity is
``(asset_id, fiscal_year, fiscal_quarter)``, a composite primary key rather
than a surrogate ``id`` — one row per company per reporting period, replaced
in place on a 정정공시 restatement (see
``src/adapters/financial_statement_repository.py``). ``rcept_no`` is
additionally UNIQUE — it identifies the specific DART disclosure document a
row's figures came from.

Revision ID: d2a6f83e1c47
Revises: bfb3e5e201c3
Create Date: 2026-08-04 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2a6f83e1c47"
down_revision: str | Sequence[str] | None = "bfb3e5e201c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_FISCAL_QUARTER_ENUM = postgresql.ENUM(
    "Q1", "H1", "Q3", "ANNUAL", name="fiscal_quarter", create_type=False
)
_CONSOLIDATED_TYPE_ENUM = postgresql.ENUM(
    "CFS", "OFS", name="consolidated_type", create_type=False
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
    _create_enum_type_idempotent("fiscal_quarter", ("Q1", "H1", "Q3", "ANNUAL"))
    _create_enum_type_idempotent("consolidated_type", ("CFS", "OFS"))

    op.create_table(
        "financial_statements",
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("assets.id"), nullable=False),
        sa.Column("fiscal_year", sa.Integer(), nullable=False),
        sa.Column("fiscal_quarter", _FISCAL_QUARTER_ENUM, nullable=False),
        sa.Column("consolidated_type", _CONSOLIDATED_TYPE_ENUM, nullable=False),
        sa.Column("revenue", sa.Numeric(24, 2), nullable=True),
        sa.Column("operating_income", sa.Numeric(24, 2), nullable=True),
        sa.Column("net_income", sa.Numeric(24, 2), nullable=True),
        sa.Column("total_assets", sa.Numeric(24, 2), nullable=True),
        sa.Column("total_liabilities", sa.Numeric(24, 2), nullable=True),
        sa.Column("total_equity", sa.Numeric(24, 2), nullable=True),
        sa.Column("disclosed_at", sa.Date(), nullable=False),
        sa.Column("rcept_no", sa.String(20), nullable=False),
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
        sa.PrimaryKeyConstraint("asset_id", "fiscal_year", "fiscal_quarter"),
        sa.UniqueConstraint("rcept_no", name="uq_financial_statements_rcept_no"),
    )


def downgrade() -> None:
    op.drop_table("financial_statements")
    op.execute("DROP TYPE IF EXISTS consolidated_type")
    op.execute("DROP TYPE IF EXISTS fiscal_quarter")
