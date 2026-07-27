"""add unreachable instance status

Revision ID: c1d24ef9a8b7
Revises: b9a11d39f9d1
Create Date: 2026-07-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c1d24ef9a8b7"
down_revision: str | None = "b9a11d39f9d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TYPE instance_status ADD VALUE IF NOT EXISTS 'unreachable'")


def downgrade() -> None:
    # PostgreSQL does not support removing an enum value safely. Keeping the
    # superset is preferable to a table/type rewrite that could lose live data.
    pass
