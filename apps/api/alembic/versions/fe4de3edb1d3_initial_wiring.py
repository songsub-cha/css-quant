"""initial wiring

No schema changes. This revision only proves the Alembic wiring
(config -> psycopg 3 engine -> migrations) works end to end; the domain
models it will later track don't exist yet.

Revision ID: fe4de3edb1d3
Revises:
Create Date: 2026-07-21 22:33:19.023103

"""

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "fe4de3edb1d3"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
