"""Shared column helpers and enums.

Every table uses a UUID primary key and timezone-aware timestamps. Neither is
negotiable later without a migration, so both are settled here.
"""

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

import sqlalchemy as sa
from sqlmodel import Field


# These return SQLModel FieldInfo, annotated Any so `x: UUID = uuid_pk()` checks.
def uuid_pk() -> Any:
    return Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        sa_type=sa.Uuid,
    )


def utc_now() -> datetime:
    return datetime.now(UTC)


def created_at_column() -> Any:
    return Field(
        default_factory=utc_now,
        sa_type=sa.DateTime(timezone=True),
        nullable=False,
    )


def optional_timestamp() -> Any:
    return Field(
        default=None,
        sa_type=sa.DateTime(timezone=True),
        nullable=True,
    )


def pg_enum(enum_cls: type[StrEnum], name: str) -> sa.Enum:
    """A Postgres enum that stores the member VALUE, not the member name.

    SQLAlchemy persists enum *names* by default, which would put "QUEUED" in the
    column while the PRD, the API, and every log line say "queued". Anyone
    reading the database directly would see a second vocabulary. values_callable
    fixes that.
    """
    return sa.Enum(
        enum_cls,
        name=name,
        values_callable=lambda cls: [member.value for member in cls],
    )


class ServiceKind(StrEnum):
    APP = "app"
    DATABASE = "database"
    # Phase 5.5. Nothing creates a static service in Phase 1, but the value
    # exists so the enum does not need a migration later.
    STATIC = "static"


class NodeStatus(StrEnum):
    HEALTHY = "healthy"
    UNREACHABLE = "unreachable"
    DRAINING = "draining"


class DeploymentStatus(StrEnum):
    QUEUED = "queued"
    BUILDING = "building"
    DEPLOYING = "deploying"
    LIVE = "live"
    FAILED = "failed"
    SUPERSEDED = "superseded"

    @property
    def is_terminal(self) -> bool:
        return self in {
            DeploymentStatus.LIVE,
            DeploymentStatus.FAILED,
            DeploymentStatus.SUPERSEDED,
        }


class InstanceStatus(StrEnum):
    STARTING = "starting"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DRAINING = "draining"
    STOPPED = "stopped"


class DomainTargetType(StrEnum):
    # Railway semantics: follows whatever Deployment is currently live.
    SERVICE = "service"
    # Vercel semantics: pinned to one immutable Deployment forever.
    DEPLOYMENT = "deployment"
