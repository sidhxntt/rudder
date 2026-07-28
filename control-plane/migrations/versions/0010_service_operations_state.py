"""persist versioned desired/observed service operations state

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _add_enum_values() -> None:
    """PostgreSQL enums need an explicit additive migration; SQLite does not."""
    if op.get_bind().dialect.name != "postgresql":
        return
    # PostgreSQL supports ADD VALUE IF NOT EXISTS on supported Rudder versions.
    # Execute in autocommit mode because older PostgreSQL releases cannot use a
    # newly added enum value until the surrounding transaction has committed.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE operation_kind ADD VALUE IF NOT EXISTS 'configure'")
        op.execute("ALTER TYPE operation_status ADD VALUE IF NOT EXISTS 'cancelled'")


def upgrade() -> None:
    _add_enum_values()
    op.create_table(
        "service_operations_state",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("service_id", sa.Uuid(), nullable=False),
        sa.Column("desired", sa.JSON(), nullable=False),
        sa.Column("observed", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "pending_reconciliation",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["service_id"], ["service.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("service_id", name="uq_service_operations_state_service"),
    )
    op.create_index(
        "ix_service_operations_state_service_id",
        "service_operations_state",
        ["service_id"],
    )
    op.create_index(
        "ix_service_operations_state_pending_reconciliation",
        "service_operations_state",
        ["pending_reconciliation"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_service_operations_state_pending_reconciliation",
        table_name="service_operations_state",
    )
    op.drop_index("ix_service_operations_state_service_id", table_name="service_operations_state")
    op.drop_table("service_operations_state")
    # PostgreSQL does not support removing individual enum values. Keeping the
    # additive vocabulary is intentional and makes rolling migrations safe.
