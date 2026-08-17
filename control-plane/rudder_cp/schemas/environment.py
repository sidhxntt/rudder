"""Request/response types for Environment."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from rudder_cp.services.naming import NAME_DESCRIPTION, ResourceName


class EnvironmentCreate(BaseModel):
    """Body of ``POST /projects/{project_id}/environments``."""

    name: ResourceName = Field(description=NAME_DESCRIPTION)
    is_production: bool = False


class EnvironmentUpdate(BaseModel):
    """Body of ``PATCH /environments/{id}``. Absent fields are left alone."""

    name: ResourceName | None = None
    is_production: bool | None = None


class EnvironmentReplace(BaseModel):
    """Body of ``PUT /environments/{id}``."""

    name: ResourceName = Field(description=NAME_DESCRIPTION)
    is_production: bool = False


class EnvironmentClone(BaseModel):
    """Requested target for an atomic environment graph clone."""

    name: ResourceName = Field(description=NAME_DESCRIPTION)
    # PR automation pins cloned services to the PR head branch.  Manual clones
    # retain their source branches.
    source_branch: str | None = Field(default=None, min_length=1, max_length=255)
    github_pr_number: int | None = Field(default=None, ge=1)


class EnvironmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    is_production: bool
    github_pr_number: int | None
    created_at: datetime
