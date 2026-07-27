"""Schemas for the node management API.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class NodeRegistrationRequest(BaseModel):
    hostname: str
    ip_address: str = Field(min_length=1, max_length=45)
    cpu_total: float = Field(gt=0)
    memory_total_mb: int = Field(gt=0)


class InstanceStatus(StrEnum):
    """Instance.status vocabulary from PRD "Data Model"."""

    STARTING = "starting"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNREACHABLE = "unreachable"
    DRAINING = "draining"
    STOPPED = "stopped"


class ContainerState(BaseModel):
    """Observed actual state of one container, sent by the agent."""

    id: str
    name: str
    status: InstanceStatus
    docker_status: str = Field(description="Raw Docker State.Status, unmapped")
    docker_health: str | None = Field(
        default=None, description="Raw Docker State.Health.Status when a HEALTHCHECK exists"
    )
    exit_code: int | None = None
    started_at: str | None = None
    ip_address: str | None = Field(default=None, description="IP on the attached docker network")
    image: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)


class HeartbeatRequest(BaseModel):
    hostname: str
    containers: list[ContainerState]


# Schemas for API responses
class InstanceRead(BaseModel):
    id: uuid.UUID
    deployment_id: uuid.UUID
    node_id: uuid.UUID
    container_id: str | None
    status: InstanceStatus
    created_at: datetime
    started_at: datetime | None
    stopped_at: datetime | None


class NodeStatusRead(StrEnum):
    HEALTHY = "healthy"
    UNREACHABLE = "unreachable"
    DRAINING = "draining"


class NodeRead(BaseModel):
    id: uuid.UUID
    hostname: str
    ip_address: str
    status: NodeStatusRead
    cpu_total: float
    memory_total_mb: int
    cpu_allocated: float
    memory_allocated_mb: int
    last_heartbeat_at: datetime | None
    created_at: datetime
    reported_state: dict | None


class NodeReadWithInstances(NodeRead):
    instances: list[InstanceRead] = []
