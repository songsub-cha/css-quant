"""add job_runs created_at/updated_at

Chains after ffbe282d9f4f (job_runs). SoT C3 L520 requires every table to
carry ``id UUID PK`` + ``created_at``/``updated_at timestamptz`` — job_runs
was the one table missing the pair (C4's field list documents additional
observability columns, not an opt-out from the C3 baseline). Both columns
get ``server_default=now()`` so the ``NOT NULL`` addition backfills existing
rows for free; there are no operational job_runs rows yet in Phase 2, so
this is a formality rather than a real backfill concern.

Revision ID: 2b904345db6d
Revises: ffbe282d9f4f
Create Date: 2026-07-29 08:16:54.584349

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2b904345db6d"
down_revision: str | Sequence[str] | None = "ffbe282d9f4f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "job_runs",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "job_runs",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("job_runs", "updated_at")
    op.drop_column("job_runs", "created_at")
