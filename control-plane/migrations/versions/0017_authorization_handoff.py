"""persist one-time authorization handoffs

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "authorization_handoff",
        sa.Column("id", sa.String(length=255), nullable=False),
        sa.Column("token", sa.Text(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_authorization_handoff_expires_at",
        "authorization_handoff",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_authorization_handoff_expires_at", table_name="authorization_handoff")
    op.drop_table("authorization_handoff")
