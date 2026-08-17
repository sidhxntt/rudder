"""track ephemeral GitHub pull-request environments

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("environment", sa.Column("github_pr_number", sa.Integer(), nullable=True))
    op.create_index("ix_environment_github_pr_number", "environment", ["github_pr_number"])


def downgrade() -> None:
    op.drop_index("ix_environment_github_pr_number", table_name="environment")
    op.drop_column("environment", "github_pr_number")
