"""enforce service operation idempotency keys

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Existing records predate the HTTP idempotency contract, so the column is
    # nullable for their audit history. New API writes always set it.
    op.add_column(
        "service_operation",
        sa.Column("idempotency_key", sa.String(length=256), nullable=True),
    )
    op.create_index(
        "ix_service_operation_idempotency_key",
        "service_operation",
        ["idempotency_key"],
    )
    # SQLite (used by the migration suite and local smoke tests) cannot add a
    # table constraint in place, while PostgreSQL can. Alembic's batch mode
    # gives both the same durable unique-key contract.
    with op.batch_alter_table("service_operation") as batch:
        batch.create_unique_constraint(
            "uq_service_operation_service_idempotency_key",
            ["service_id", "idempotency_key"],
        )


def downgrade() -> None:
    with op.batch_alter_table("service_operation") as batch:
        batch.drop_constraint("uq_service_operation_service_idempotency_key", type_="unique")
    op.drop_index("ix_service_operation_idempotency_key", table_name="service_operation")
    op.drop_column("service_operation", "idempotency_key")
