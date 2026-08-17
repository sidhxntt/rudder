"""persist GitHub profile avatar URL

Revision ID: 0016
Revises: 0015
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user", sa.Column("github_avatar_url", sa.String(length=2048), nullable=True))


def downgrade() -> None:
    op.drop_column("user", "github_avatar_url")
