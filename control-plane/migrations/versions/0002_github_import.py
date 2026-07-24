"""track confirmed GitHub repository imports

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "github_import",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("installation_id", sa.Integer(), nullable=False),
        sa.Column("repository", sa.String(length=255), nullable=False),
        sa.Column("branch", sa.String(length=255), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=False),
        sa.Column("app_service_id", sa.Uuid(), nullable=False),
        sa.Column("postgres_service_id", sa.Uuid(), nullable=True),
        sa.Column("redis_service_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["project.id"]),
        sa.ForeignKeyConstraint(["app_service_id"], ["service.id"]),
        sa.ForeignKeyConstraint(["postgres_service_id"], ["service.id"]),
        sa.ForeignKeyConstraint(["redis_service_id"], ["service.id"]),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("github_import")
