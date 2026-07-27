"""Boundary types for the agent HTTP API.

The control plane resolves and decrypts variables, picks the host, and decides
what should run. Everything in this module is what it tells the agent, or what
the agent observed. No desired state is stored here.
"""

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field


class InstanceStatus(StrEnum):
    """Instance.status vocabulary from PRD "Data Model". The agent reports into
    this vocabulary; it does not invent states of its own."""

    STARTING = "starting"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    DRAINING = "draining"
    STOPPED = "stopped"


Port = Annotated[int, Field(ge=1, le=65535)]


class ContainerSpec(BaseModel):
    """POST /containers request body.

    `env` arrives already resolved and decrypted — the agent does no variable
    resolution. Deployed containers publish no host ports; Traefik reaches them
    over `network`.
    """

    # Unknown keys are ignored, not rejected: the control plane is allowed to
    # grow the spec without a lockstep agent deploy. Every field the agent
    # actually needs is required, so a typo still fails loudly.
    model_config = {"extra": "ignore"}

    image: str = Field(min_length=1)
    name: str = Field(min_length=1)
    env: dict[str, str] = Field(default_factory=dict)
    container_port: Port
    cpu_limit: float = Field(gt=0, description="CPU cores, e.g. 0.5")
    memory_limit_mb: int = Field(ge=6, description="Docker's floor is 6 MB")
    network: str = Field(min_length=1)
    labels: dict[str, str] = Field(default_factory=dict)
    network_aliases: list[str] = Field(default_factory=list)
    volumes: dict[str, dict[str, str]] = Field(default_factory=dict)
    command: list[str] | None = None


class ContainerState(BaseModel):
    """Observed actual state of one container. Response of POST /containers and
    GET /containers/{id}."""

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


class DeleteResult(BaseModel):
    """Response of DELETE /containers/{id}. Idempotent: deleting a container
    that is already gone is a success with `removed=false`."""

    id: str
    status: InstanceStatus
    removed: bool
    drained_seconds: float


class HealthProbeRequest(BaseModel):
    """POST /containers/{id}/health request body.

    One probe, one result. The D12 poll loop (60s timeout, 2s interval, 5s start
    grace, 1 success required) belongs to the control plane.
    """

    model_config = {"extra": "ignore"}

    path: str = "/"
    protocol: Literal["http", "tcp"] = "http"
    port: Port
    timeout_seconds: float = Field(default=5.0, gt=0, le=60)
    network: str | None = Field(
        default=None,
        description="Which attached network's IP to probe. Defaults to the only one.",
    )


class HealthProbeResult(BaseModel):
    """Outcome of exactly one probe. A failed probe is a 200 response with
    `ok=false`, not an HTTP error — failure is an ordinary outcome."""

    ok: bool
    status_code: int | None = None
    reason: str | None = None
    latency_ms: float
    probed_url: str | None = None


ComposeProjectName = Annotated[
    str,
    Field(pattern=r"^[a-z][a-z0-9-]{0,62}$", description="Rudder-owned Compose namespace"),
]


class ComposeUpRequest(BaseModel):
    """One validated manifest to write below the agent-owned state directory."""

    model_config = {"extra": "forbid"}

    project_name: ComposeProjectName
    manifest: str = Field(min_length=1, max_length=64 * 1024)


class ComposeProjectRequest(BaseModel):
    model_config = {"extra": "forbid"}

    project_name: ComposeProjectName


class ComposeResult(BaseModel):
    project_name: str
    log: str


class ComposeServiceState(BaseModel):
    service: str
    container_id: str | None = None
    status: str
    health: str | None = None
    exit_code: int | None = None
