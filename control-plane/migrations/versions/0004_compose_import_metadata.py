"""persist resolved Compose metadata for GitHub imports

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import context, op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add nullable first so existing confirmed imports can receive a stable,
    # deterministic project namespace before the non-null constraint lands.
    op.add_column("github_import", sa.Column("compose_source", sa.String(length=32), nullable=True))
    op.add_column("github_import", sa.Column("compose_manifest", sa.Text(), nullable=True))
    op.add_column(
        "github_import", sa.Column("compose_project_name", sa.String(length=63), nullable=True)
    )
    bind = op.get_bind()
    statement = sa.text(
        "UPDATE github_import "
        "SET compose_source = 'generated', "
        "compose_manifest = 'services: {}\n', "
        "compose_project_name = 'rudder-' || replace(CAST(project_id AS TEXT), '-', '')"
    )
    # Alembic's offline SQL renderer has no DBAPI parameter values and would
    # otherwise emit NULL for a bound manifest. The literal is safe: it is a
    # fixed, internal migration value rather than user-controlled content.
    if context.is_offline_mode():
        op.execute(statement)
    else:
        bind.execute(statement)
    with op.batch_alter_table("github_import") as batch:
        batch.alter_column("compose_source", existing_type=sa.String(length=32), nullable=False)
        batch.alter_column("compose_manifest", existing_type=sa.Text(), nullable=False)
        batch.alter_column(
            "compose_project_name", existing_type=sa.String(length=63), nullable=False
        )
        batch.create_index(
            "ix_github_import_compose_project_name", ["compose_project_name"], unique=True
        )


def downgrade() -> None:
    with op.batch_alter_table("github_import") as batch:
        batch.drop_index("ix_github_import_compose_project_name")
        batch.drop_column("compose_project_name")
        batch.drop_column("compose_manifest")
        batch.drop_column("compose_source")
