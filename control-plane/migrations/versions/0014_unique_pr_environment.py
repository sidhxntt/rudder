"""make PR environment delivery idempotency durable

Revision ID: 0014
Revises: 0013
Create Date: 2026-08-16
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_environment_project_github_pr",
        "environment",
        ["project_id", "github_pr_number"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_environment_project_github_pr", "environment", type_="unique")
