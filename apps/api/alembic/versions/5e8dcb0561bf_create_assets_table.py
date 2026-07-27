"""create assets table

Third real schema revision (SoT C3) — chains after 182348023054
(password reset tokens). First revision to introduce SAEnum columns in
this repo, so it follows SoT B5.2/B5.3 to the letter: enum columns use
``postgresql.ENUM(..., create_type=False)`` and the Postgres enum types
themselves are created via idempotent ``DO $$ ... EXCEPTION WHEN
duplicate_object`` blocks rather than ``CREATE TYPE`` directly, so this
revision can be re-run safely if a prior partial apply left a type behind.

Asset identity is ticker + listing span (SoT C3): a KRX ticker code can be
reused after delisting, so the unique constraint applies only to active
rows — a partial index on ``(ticker, market) WHERE is_active`` rather than
a plain unique constraint. ``is_active``/``is_managed``/``is_alert`` are
``NOT NULL`` with a ``server_default`` so the partial index predicate never
has to reckon with a NULL ``is_active``.

Revision ID: 5e8dcb0561bf
Revises: 182348023054
Create Date: 2026-07-28 08:18:14.831881

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5e8dcb0561bf"
down_revision: str | Sequence[str] | None = "182348023054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MARKET_ENUM = postgresql.ENUM("KR", name="market", create_type=False)
_ASSET_TYPE_ENUM = postgresql.ENUM("STOCK", "ETF", name="asset_type", create_type=False)
_EXCHANGE_ENUM = postgresql.ENUM("KOSPI", "KOSDAQ", name="exchange", create_type=False)


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
    _create_enum_type_idempotent("market", ("KR",))
    _create_enum_type_idempotent("asset_type", ("STOCK", "ETF"))
    _create_enum_type_idempotent("exchange", ("KOSPI", "KOSDAQ"))

    op.create_table(
        "assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("market", _MARKET_ENUM, nullable=False),
        sa.Column("asset_type", _ASSET_TYPE_ENUM, nullable=False),
        sa.Column("exchange", _EXCHANGE_ENUM, nullable=False),
        sa.Column("sector", sa.String(length=100), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="KRW"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("listed_at", sa.Date(), nullable=True),
        sa.Column("delisted_at", sa.Date(), nullable=True),
        sa.Column("is_managed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_alert", sa.Boolean(), nullable=False, server_default=sa.false()),
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
    )
    op.create_index(
        "uq_assets_ticker_market_active",
        "assets",
        ["ticker", "market"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )


def downgrade() -> None:
    op.drop_index("uq_assets_ticker_market_active", table_name="assets")
    op.drop_table("assets")
    op.execute("DROP TYPE IF EXISTS exchange")
    op.execute("DROP TYPE IF EXISTS asset_type")
    op.execute("DROP TYPE IF EXISTS market")
