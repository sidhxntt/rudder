"""persist GitHub OAuth identities

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user", sa.Column("github_id", sa.BigInteger(), nullable=True))
    op.add_column("user", sa.Column("github_login", sa.String(length=255), nullable=True))
    op.create_index("ix_user_github_id", "user", ["github_id"], unique=True)


def downgrade() -> None:
    has_github_identities = op.get_bind().execute(
        sa.text('SELECT 1 FROM "user" WHERE github_id IS NOT NULL LIMIT 1')
    ).scalar()
    if has_github_identities is not None:
        raise RuntimeError(
            "Cannot downgrade GitHub OAuth identities while users have a github_id. "
            "Migrate or remove those identities explicitly before downgrading."
        )
    op.drop_index("ix_user_github_id", table_name="user")
    op.drop_column("user", "github_login")
    op.drop_column("user", "github_id")
