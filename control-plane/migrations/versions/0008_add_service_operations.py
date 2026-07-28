"""persist typed Kubernetes service operation records

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


operation_kind = sa.Enum(
    "scale",
    "resources",
    "autoscaling",
    "placement",
    "rollout",
    "rollback",
    "backup",
    "restore",
    "read_replica",
    "storage",
    "schedule",
    "job",
    "observability",
    name="operation_kind",
)
operation_status = sa.Enum(
    "pending", "progressing", "healthy", "degraded", "failed", name="operation_status"
)


def upgrade() -> None:
    # ``op.create_table`` owns creation of its named PostgreSQL enums. Creating
    # them explicitly here as well would emit duplicate CREATE TYPE statements
    # in Alembic's offline SQL output.
    op.create_table(
        "service_operation",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("kind", operation_kind, nullable=False),
        sa.Column("status", operation_status, nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=True),
        sa.Column("requested", sa.JSON(), nullable=False),
        sa.Column("observed", sa.JSON(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["service_id"], ["service.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_service_operation_service_id", "service_operation", ["service_id"])
    op.create_index("ix_service_operation_kind", "service_operation", ["kind"])
    op.create_index("ix_service_operation_status", "service_operation", ["status"])
    op.create_index("ix_service_operation_request_hash", "service_operation", ["request_hash"])
    op.create_index(
        "ix_service_operation_service_request",
        "service_operation",
        ["service_id", "request_hash"],
    )


def downgrade() -> None:
    op.drop_index("ix_service_operation_service_request", table_name="service_operation")
    op.drop_index("ix_service_operation_request_hash", table_name="service_operation")
    op.drop_index("ix_service_operation_status", table_name="service_operation")
    op.drop_index("ix_service_operation_kind", table_name="service_operation")
    op.drop_index("ix_service_operation_service_id", table_name="service_operation")
    op.drop_table("service_operation")
    bind = op.get_bind()
    operation_status.drop(bind, checkfirst=True)
    operation_kind.drop(bind, checkfirst=True)
