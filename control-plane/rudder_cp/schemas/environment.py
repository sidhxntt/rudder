"""Request/response types for Environment."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from rudder_cp.services.naming import NAME_DESCRIPTION, ResourceName


class EnvironmentCreate(BaseModel):
    """Body of ``POST /projects/{project_id}/environments``.

    ``wg_subnet`` is not accepted from the client: it is a server-allocated
    resource (see ``services.environments.allocate_wg_subnet``).
    """

    name: ResourceName = Field(description=NAME_DESCRIPTION)
    is_production: bool = False


class EnvironmentUpdate(BaseModel):
    """Body of ``PATCH /environments/{id}``. Absent fields are left alone."""

    name: ResourceName | None = None
    is_production: bool | None = None


class EnvironmentReplace(BaseModel):
    """Body of ``PUT /environments/{id}``.

    ``wg_subnet`` is intentionally absent. It is allocated once at create time
    and never renumbered, so it cannot participate in a full replacement
    without breaking the mesh in Phase 3.
    """

    name: ResourceName = Field(description=NAME_DESCRIPTION)
    is_production: bool = False


class EnvironmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    is_production: bool
    wg_subnet: str | None = Field(
        default=None,
        description="Server-allocated /24 for this environment's WireGuard mesh (Phase 3).",
    )
    created_at: datetime
