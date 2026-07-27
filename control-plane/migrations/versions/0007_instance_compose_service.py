"""persist immutable Compose service identity on release instances

Revision ID: 0007
Revises: c1d24ef9a8b7
Create Date: 2026-07-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "c1d24ef9a8b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("instance", sa.Column("compose_service", sa.String(length=63), nullable=True))


def downgrade() -> None:
    op.drop_column("instance", "compose_service")
