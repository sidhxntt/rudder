"""remove obsolete WireGuard environment allocation

Phase 4 uses Kubernetes namespaces and NetworkPolicies for environment
isolation.  The historical WireGuard CIDR was never a runtime dependency and
must not remain an API or database resource.

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("environment", "wg_subnet")


def downgrade() -> None:
    op.add_column("environment", sa.Column("wg_subnet", sa.String(length=32), nullable=True))
