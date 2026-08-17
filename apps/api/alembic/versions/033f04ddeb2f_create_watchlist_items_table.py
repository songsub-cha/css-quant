"""create watchlist_items table

Eleventh real schema revision (SoT A5.2/C3) — chains after b8b6628e93d4
(ai_scores). This is the repo's second *lowercase-valued* persisted enum
(``watch``/``exclude``) after ``job_run_status`` (ffbe282d9f4f) — per SoT
B5.2/B5.3, the model's ``values_callable``, this migration's
``postgresql.ENUM`` labels, and the idempotent ``DO $$ CREATE TYPE`` labels
below all agree on lowercase.

Identity is ``(user_id, asset_id)`` (SoT C3's ``UNIQUE(user_id, asset_id)``)
enforced via a named unique constraint on a surrogate ``id`` primary key —
same shape as ``password_reset_tokens`` (surrogate PK + separate unique
constraint), not a composite PK like ``ai_scores``. FK to both
``users.id`` and ``assets.id`` — a watchlist row always belongs to one
owner's decision about one listed instrument.

Revision ID: 033f04ddeb2f
Revises: b8b6628e93d4
Create Date: 2026-08-17 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "033f04ddeb2f"
down_revision: str | Sequence[str] | None = "b8b6628e93d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_WATCHLIST_KIND_ENUM = postgresql.ENUM("watch", "exclude", name="watchlist_kind", create_type=False)


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
    _create_enum_type_idempotent("watchlist_kind", ("watch", "exclude"))

    op.create_table(
        "watchlist_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", _WATCHLIST_KIND_ENUM, nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_watchlist_items_user_id"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], name="fk_watchlist_items_asset_id"),
        sa.UniqueConstraint("user_id", "asset_id", name="uq_watchlist_items_user_id_asset_id"),
    )


def downgrade() -> None:
    op.drop_table("watchlist_items")
    op.execute("DROP TYPE IF EXISTS watchlist_kind")
