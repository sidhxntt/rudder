"""Durable, auditable intent for service operations.

The operation table is deliberately generic: every runtime mutation is recorded
as typed request JSON and reconciled observation JSON.  It never holds secrets;
credential material continues to live in ``variable`` records.
"""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from rudder_cp.models.base import (
    created_at_column,
    optional_timestamp,
    pg_enum,
    utc_now,
    uuid_pk,
)


class OperationKind(StrEnum):
    CONFIGURE = "configure"
    SCALE = "scale"
    RESOURCES = "resources"
    AUTOSCALING = "autoscaling"
    PLACEMENT = "placement"
    ROLLOUT = "rollout"
    ROLLBACK = "rollback"
    BACKUP = "backup"
    RESTORE = "restore"
    READ_REPLICA = "read_replica"
    STORAGE = "storage"
    SCHEDULE = "schedule"
    JOB = "job"
    OBSERVABILITY = "observability"


class OperationStatus(StrEnum):
    PENDING = "pending"
    PROGRESSING = "progressing"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {
            OperationStatus.HEALTHY,
            OperationStatus.DEGRADED,
            OperationStatus.FAILED,
            OperationStatus.CANCELLED,
        }


class ServiceOperationsState(SQLModel, table=True):
    """Current desired state and last observed reconciliation state for a service.

    ``ServiceOperation`` remains the immutable audit log. This one-row aggregate
    lets the reconciler consume intent exactly once per version without reading
    transient request data or overloading source/build configuration.
    """

    __tablename__ = "service_operations_state"
    __table_args__ = (
        sa.UniqueConstraint("service_id", name="uq_service_operations_state_service"),
    )

    id: uuid.UUID = uuid_pk()
    service_id: uuid.UUID = Field(
        foreign_key="service.id", sa_type=sa.Uuid, nullable=False, index=True
    )
    desired: dict[str, Any] = Field(
        default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False)
    )
    observed: dict[str, Any] = Field(
        default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False)
    )
    version: int = Field(default=0, nullable=False)
    pending_reconciliation: bool = Field(default=False, nullable=False, index=True)
    created_at: datetime = created_at_column()
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_type=sa.DateTime(timezone=True),
        nullable=False,
    )


class ServiceOperation(SQLModel, table=True):
    """One requested service operation and the reconciler's observed result."""

    __tablename__ = "service_operation"
    __table_args__ = (
        # PostgreSQL permits multiple NULLs in a unique constraint.  That lets
        # maintenance/audit records omit a hash while API-originated requests
        # are durably idempotent per service.
        sa.UniqueConstraint(
            "service_id",
            "request_hash",
            name="uq_service_operation_service_request_hash",
        ),
        sa.UniqueConstraint(
            "service_id",
            "idempotency_key",
            name="uq_service_operation_service_idempotency_key",
        ),
    )

    id: uuid.UUID = uuid_pk()
    service_id: uuid.UUID = Field(
        foreign_key="service.id", sa_type=sa.Uuid, nullable=False, index=True
    )
    kind: OperationKind = Field(
        sa_column=sa.Column(pg_enum(OperationKind, "operation_kind"), nullable=False, index=True)
    )
    status: OperationStatus = Field(
        default=OperationStatus.PENDING,
        sa_column=sa.Column(
            pg_enum(OperationStatus, "operation_status"), nullable=False, index=True
        ),
    )
    # Filled by the API when it has a stable hash of the request.  The initial
    # schema keeps it nullable for audit records created by migrations/tools.
    request_hash: str | None = Field(default=None, max_length=64, index=True)
    # The raw key is persisted separately from its hash so that reusing a key
    # for a different endpoint or payload can be rejected rather than treated
    # as an unrelated request. Historical audit records may omit it.
    idempotency_key: str | None = Field(default=None, max_length=256, index=True)
    requested: dict[str, Any] = Field(
        sa_column=sa.Column(sa.JSON, nullable=False),
    )
    observed: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=sa.Column(sa.JSON, nullable=False),
    )
    error_message: str | None = Field(default=None, sa_column=sa.Column(sa.Text, nullable=True))
    created_at: datetime = created_at_column()
    completed_at: datetime | None = optional_timestamp()
