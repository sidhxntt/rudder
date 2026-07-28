"""store trusted service operation capabilities separately from build config

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "service_managed_capabilities",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("database_engine", sa.String(length=32), nullable=True),
        sa.Column("data_role", sa.String(length=32), nullable=True),
        sa.Column("allowed_job_commands", sa.JSON(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="import"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["service_id"], ["service.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("service_id", name="uq_service_managed_capabilities_service"),
    )
    op.create_index(
        "ix_service_managed_capabilities_service_id",
        "service_managed_capabilities",
        ["service_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_service_managed_capabilities_service_id",
        table_name="service_managed_capabilities",
    )
    op.drop_table("service_managed_capabilities")
