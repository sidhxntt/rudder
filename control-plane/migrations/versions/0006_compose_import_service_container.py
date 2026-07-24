"""persist active Compose container for imported service graph members

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "github_import_service",
        sa.Column("container_id", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("github_import_service", "container_id")
