"""persist Compose service graph for GitHub imports

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "github_import_service",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("github_import_id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("compose_service", sa.String(length=63), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False),
        sa.Column("is_public", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["github_import_id"], ["github_import.id"]),
        sa.ForeignKeyConstraint(["service_id"], ["service.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("github_import_id", "compose_service", name="uq_import_compose_service"),
        sa.UniqueConstraint("service_id", name="uq_import_service"),
    )
    op.create_index(
        "ix_github_import_service_github_import_id",
        "github_import_service",
        ["github_import_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_github_import_service_github_import_id", "github_import_service")
    op.drop_table("github_import_service")
