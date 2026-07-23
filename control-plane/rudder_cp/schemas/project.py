"""Request/response types for Project. Separate from the table by design."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from rudder_cp.services.naming import ProjectName


class ProjectCreate(BaseModel):
    """Body of ``POST /projects``.

    Creating a project also creates its ``production`` environment — a project
    with no environment cannot hold a service, and every phase document assumes
    ``production`` exists.
    """

    name: ProjectName = Field(description="Display name. Not a hostname component.")


class ProjectUpdate(BaseModel):
    """Body of ``PATCH /projects/{id}``. Absent fields are left alone."""

    name: ProjectName | None = None


class ProjectReplace(BaseModel):
    """Body of ``PUT /projects/{id}``. Every writable field, always.

    ``owner_id`` and ``created_at`` are server-owned and are not writable, so a
    PUT of the same body twice is genuinely the same result.
    """

    name: ProjectName


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    owner_id: uuid.UUID
    created_at: datetime
