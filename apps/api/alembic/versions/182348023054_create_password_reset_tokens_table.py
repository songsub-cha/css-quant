"""create password reset tokens table

Second real schema revision (SoT A5.1) — chains after fd873a83aa76
(users table). ``token_hash`` stores only a sha256 digest of the raw
reset token (src.domain.password_reset.hash_reset_token); the raw token
itself is never persisted.

Revision ID: 182348023054
Revises: fd873a83aa76
Create Date: 2026-07-25 13:39:36.104101

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "182348023054"
down_revision: str | Sequence[str] | None = "fd873a83aa76"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_password_reset_tokens_user_id"),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
    )


def downgrade() -> None:
    op.drop_table("password_reset_tokens")
