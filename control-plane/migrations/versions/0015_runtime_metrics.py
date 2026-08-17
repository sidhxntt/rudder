"""store bounded container metric samples for Phase 6

Revision ID: 0015
Revises: 0014
Create Date: 2026-08-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "runtime_metric",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("instance_id", sa.Uuid(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolution_seconds", sa.Integer(), nullable=False),
        sa.Column("cpu_percent", sa.Float(), nullable=False),
        sa.Column("memory_bytes", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["instance_id"], ["instance.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "instance_id",
            "captured_at",
            "resolution_seconds",
            name="uq_runtime_metric_sample",
        ),
    )
    op.create_index("ix_runtime_metric_instance_id", "runtime_metric", ["instance_id"])
    op.create_index("ix_runtime_metric_captured_at", "runtime_metric", ["captured_at"])
    op.create_index(
        "ix_runtime_metric_instance_tier_time",
        "runtime_metric",
        ["instance_id", "resolution_seconds", "captured_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_runtime_metric_instance_tier_time", table_name="runtime_metric")
    op.drop_index("ix_runtime_metric_captured_at", table_name="runtime_metric")
    op.drop_index("ix_runtime_metric_instance_id", table_name="runtime_metric")
    op.drop_table("runtime_metric")
