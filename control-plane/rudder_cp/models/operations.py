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

from rudder_cp.models.base import created_at_column, optional_timestamp, pg_enum, uuid_pk


class OperationKind(StrEnum):
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

    @property
    def is_terminal(self) -> bool:
        return self in {OperationStatus.HEALTHY, OperationStatus.DEGRADED, OperationStatus.FAILED}


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
