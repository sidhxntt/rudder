"""Bounded time-series samples for Phase 6 container sparklines."""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from rudder_cp.models.base import created_at_column, uuid_pk


class RuntimeMetric(SQLModel, table=True):
    """CPU/memory sample; ``resolution_seconds`` identifies its retention tier."""

    __tablename__ = "runtime_metric"
    __table_args__ = (
        sa.UniqueConstraint(
            "instance_id", "captured_at", "resolution_seconds", name="uq_runtime_metric_sample"
        ),
        sa.Index(
            "ix_runtime_metric_instance_tier_time",
            "instance_id",
            "resolution_seconds",
            "captured_at",
        ),
    )

    id: uuid.UUID = uuid_pk()
    instance_id: uuid.UUID = Field(foreign_key="instance.id", sa_type=sa.Uuid, nullable=False)
    captured_at: datetime = Field(sa_type=sa.DateTime(timezone=True), nullable=False)
    resolution_seconds: int = Field(nullable=False)
    cpu_percent: float = Field(nullable=False)
    memory_bytes: int = Field(nullable=False)
    created_at: datetime = created_at_column()
