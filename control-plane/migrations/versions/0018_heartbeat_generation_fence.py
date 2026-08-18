"""fence stale node heartbeats after deployment promotion

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "node",
        sa.Column("heartbeat_generation", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "instance",
        sa.Column(
            "missing_after_heartbeat_generation",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    # The default is only needed while existing rows are backfilled. New rows
    # must get their value from the application model rather than the database
    # silently supplying a stale sentinel forever.
    # ``batch_alter_table`` keeps the full migration chain portable to the
    # SQLite database used for local development and migration regression
    # tests; SQLite cannot issue ``ALTER COLUMN DROP DEFAULT`` directly.
    with op.batch_alter_table("node") as batch_op:
        batch_op.alter_column("heartbeat_generation", server_default=None)
    with op.batch_alter_table("instance") as batch_op:
        batch_op.alter_column("missing_after_heartbeat_generation", server_default=None)


def downgrade() -> None:
    op.drop_column("instance", "missing_after_heartbeat_generation")
    op.drop_column("node", "heartbeat_generation")
