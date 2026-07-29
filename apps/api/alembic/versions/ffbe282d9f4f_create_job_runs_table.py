"""create job_runs table

Fifth real schema revision (SoT C4) — chains after 56083c1c2a22
(market_prices). This is the repo's first *lowercase-valued* persisted enum
(``running``/``success``/``failed``/``skipped``) rather than the
uppercase-both-sides shape ``assets``' enums use, so — per SoT B5.2/B5.3 —
every one of the three places a label appears (the model's
``values_callable``, this migration's ``postgresql.ENUM`` labels, and the
idempotent ``DO $$ CREATE TYPE`` labels below) must agree on lowercase, or
inserts fail with an invalid-literal error the uppercase-both-sides enums
never surface.

No unique constraint on ``(job_name, run_date)`` — this table accumulates
one row per execution (SoT C4/D6, retries and manual reruns included), not
one row per ``(job, day)``. The non-unique index below exists only for D6's
future "detect today's un-run jobs" catch-up query; that query itself is a
later issue's scope.

Revision ID: ffbe282d9f4f
Revises: 56083c1c2a22
Create Date: 2026-07-29 12:19:35.744659

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ffbe282d9f4f"
down_revision: str | Sequence[str] | None = "56083c1c2a22"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JOB_RUN_STATUS_ENUM = postgresql.ENUM(
    "running", "success", "failed", "skipped", name="job_run_status", create_type=False
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
    _create_enum_type_idempotent("job_run_status", ("running", "success", "failed", "skipped"))

    op.create_table(
        "job_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("job_name", sa.String(length=100), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("status", _JOB_RUN_STATUS_ENUM, nullable=False, server_default="running"),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("stats", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_job_runs_job_name_run_date", "job_runs", ["job_name", "run_date"])


def downgrade() -> None:
    op.drop_index("ix_job_runs_job_name_run_date", table_name="job_runs")
    op.drop_table("job_runs")
    op.execute("DROP TYPE IF EXISTS job_run_status")
