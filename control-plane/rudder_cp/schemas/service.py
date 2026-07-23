"""Request/response types for Service."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from rudder_cp.models.base import ServiceKind
from rudder_cp.services.naming import NAME_DESCRIPTION, ResourceName

# Shared field descriptions — one definition each, so the generated SDKs read
# the same way as the API docs.
_REPO = "owner/repo on GitHub. Null for a service with no source (e.g. a database)."
_BRANCH = "Branch that a push webhook deploys from."
_DOCKERFILE = "Path to a Dockerfile in the repo. Null means one is generated."
_BUILD_CONFIG = "Free-form build knobs consumed by the builder."
_START = "Overrides the image's CMD. Null keeps the image default."
_PORT = "D1 — the port the app listens on. Traefik routes here."
_HEALTH_PATH = "Path polled until it returns 200 after a deploy."
_HEALTH_PORT = "Port for the health check. Null means use container_port (D1)."
_CANVAS = "D6 — UI-only canvas coordinate. Writable, and never a deploy trigger."


class ServiceCreate(BaseModel):
    """Body of ``POST /environments/{environment_id}/services``.

    Creating a service also creates its D15 system Domain at
    ``{name}.{environment}.{base_domain}``.
    """

    name: ResourceName = Field(description=NAME_DESCRIPTION)
    kind: ServiceKind = ServiceKind.APP

    source_repo: str | None = Field(default=None, max_length=255, description=_REPO)
    source_branch: str = Field(default="main", max_length=255, description=_BRANCH)
    dockerfile_path: str | None = Field(default=None, max_length=255, description=_DOCKERFILE)
    build_config: dict[str, Any] = Field(default_factory=dict, description=_BUILD_CONFIG)

    start_command: str | None = Field(default=None, max_length=512, description=_START)

    container_port: int = Field(default=8080, ge=1, le=65535, description=_PORT)
    health_check_path: str = Field(default="/", max_length=255, description=_HEALTH_PATH)
    health_check_port: int | None = Field(
        default=None, ge=1, le=65535, description=_HEALTH_PORT
    )

    cpu_limit: float = Field(default=1.0, gt=0, description="CPU cores.")
    memory_limit_mb: int = Field(default=512, gt=0, description="Memory cap in MiB.")
    replica_count: int = Field(default=1, ge=0, description="Desired instance count.")

    canvas_x: float = Field(default=0.0, description=_CANVAS)
    canvas_y: float = Field(default=0.0, description=_CANVAS)


class ServiceUpdate(BaseModel):
    """Body of ``PATCH /services/{id}``. Absent fields are left alone.

    Renaming rewrites the service's system domain hostname. Moving the node on
    the canvas (``canvas_x`` / ``canvas_y``) is pure metadata per D6 — it
    persists and triggers nothing.
    """

    name: ResourceName | None = None
    kind: ServiceKind | None = None

    source_repo: str | None = Field(default=None, max_length=255, description=_REPO)
    source_branch: str | None = Field(default=None, max_length=255, description=_BRANCH)
    dockerfile_path: str | None = Field(default=None, max_length=255, description=_DOCKERFILE)
    build_config: dict[str, Any] | None = Field(default=None, description=_BUILD_CONFIG)

    start_command: str | None = Field(default=None, max_length=512, description=_START)

    container_port: int | None = Field(default=None, ge=1, le=65535, description=_PORT)
    health_check_path: str | None = Field(default=None, max_length=255, description=_HEALTH_PATH)
    health_check_port: int | None = Field(default=None, ge=1, le=65535, description=_HEALTH_PORT)

    cpu_limit: float | None = Field(default=None, gt=0)
    memory_limit_mb: int | None = Field(default=None, gt=0)
    replica_count: int | None = Field(default=None, ge=0)

    canvas_x: float | None = Field(default=None, description=_CANVAS)
    canvas_y: float | None = Field(default=None, description=_CANVAS)


class ServiceReplace(ServiceCreate):
    """Body of ``PUT /services/{id}``.

    Same fields as create, same defaults. A field left out is reset to its
    default — that is what makes PUT idempotent rather than a second PATCH.
    ``environment_id`` is not replaceable: moving a service between
    environments would change its hostname, its mesh subnet and its variables,
    and is not a Phase 1 operation.
    """


class ServiceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    environment_id: uuid.UUID
    name: str
    kind: ServiceKind

    source_repo: str | None
    source_branch: str
    dockerfile_path: str | None
    build_config: dict[str, Any]

    start_command: str | None

    container_port: int
    health_check_path: str
    health_check_port: int | None

    cpu_limit: float
    memory_limit_mb: int
    replica_count: int

    canvas_x: float
    canvas_y: float

    created_at: datetime
