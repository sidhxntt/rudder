import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from rudder_cp.models.base import (
    NodeStatus,
    created_at_column,
    optional_timestamp,
    pg_enum,
    uuid_pk,
)


class Node(SQLModel, table=True):
    """A host that runs containers.

    Unused in Phase 1 — one node row is seeded for localhost so Instance rows
    have something to point at. The scheduler that reads the capacity columns
    arrives in Phase 2; the mesh columns are wired in Phase 3.

    `cpu_allocated` / `memory_allocated_mb` are the control plane's view of
    committed capacity, not the node's measured usage. They are updated when
    placement decisions are made, and they are exactly where the Phase 2
    concurrency hazards live.
    """

    __tablename__ = "node"

    id: uuid.UUID = uuid_pk()
    hostname: str = Field(sa_column=sa.Column(sa.String(255), unique=True, nullable=False))
    ip_address: str = Field(max_length=45, nullable=False)

    wg_public_key: str | None = Field(default=None, max_length=64)
    wg_ip: str | None = Field(default=None, max_length=45)

    cpu_total: float = Field(default=0.0, nullable=False)
    memory_total_mb: int = Field(default=0, nullable=False)
    cpu_allocated: float = Field(default=0.0, nullable=False)
    memory_allocated_mb: int = Field(default=0, nullable=False)

    status: NodeStatus = Field(
        default=NodeStatus.HEALTHY,
        sa_column=sa.Column(pg_enum(NodeStatus, "node_status"), nullable=False),
    )
    last_heartbeat_at: datetime | None = optional_timestamp()
    created_at: datetime = created_at_column()
