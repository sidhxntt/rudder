"""Request/response types for Domain (D15).

The table carries a CHECK constraint: exactly one of ``service_id`` /
``deployment_id`` is non-null. The client must never see that as an
IntegrityError, so the same rule is a model validator here and comes back as a
422 before any SQL is emitted.
"""

import uuid
from datetime import datetime
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rudder_cp.models.base import DomainTargetType
from rudder_cp.services.naming import HOSTNAME_DESCRIPTION, Hostname

_TLS = (
    "Null means follow RUDDER_TLS_MODE: on for 'acme', off for 'off'. "
    "Set explicitly to override."
)
_SERVICE_TARGET = "Required when target_type=service. Routes to whatever Deployment is live."
_DEPLOYMENT_TARGET = "Required when target_type=deployment. Pinned to one immutable build."


def _check_exactly_one_target(
    target_type: DomainTargetType,
    service_id: uuid.UUID | None,
    deployment_id: uuid.UUID | None,
) -> None:
    if service_id is not None and deployment_id is not None:
        raise ValueError("set exactly one of service_id / deployment_id, not both")
    if service_id is None and deployment_id is None:
        raise ValueError("set exactly one of service_id / deployment_id, neither was given")
    if target_type is DomainTargetType.SERVICE and service_id is None:
        raise ValueError("target_type=service requires service_id")
    if target_type is DomainTargetType.DEPLOYMENT and deployment_id is None:
        raise ValueError("target_type=deployment requires deployment_id")


class DomainCreate(BaseModel):
    """Body of ``POST /environments/{environment_id}/domains``.

    There is no ``is_system`` field. System domains are created by the control
    plane alongside their service and cannot be forged through this API.
    """

    hostname: Hostname = Field(description=HOSTNAME_DESCRIPTION)
    target_type: DomainTargetType = DomainTargetType.SERVICE
    service_id: uuid.UUID | None = Field(default=None, description=_SERVICE_TARGET)
    deployment_id: uuid.UUID | None = Field(default=None, description=_DEPLOYMENT_TARGET)
    tls_enabled: bool | None = Field(default=None, description=_TLS)

    @model_validator(mode="after")
    def _exactly_one_target(self) -> Self:
        _check_exactly_one_target(self.target_type, self.service_id, self.deployment_id)
        return self


class DomainUpdate(BaseModel):
    """Body of ``PATCH /domains/{id}``. Absent fields are left alone.

    Retargeting is the Phase 5 rollback primitive: an UPDATE on a Domain row,
    not a rebuild. When retargeting, send ``target_type`` together with the id
    it needs so the pair stays consistent.
    """

    hostname: Hostname | None = None
    target_type: DomainTargetType | None = None
    service_id: uuid.UUID | None = Field(default=None, description=_SERVICE_TARGET)
    deployment_id: uuid.UUID | None = Field(default=None, description=_DEPLOYMENT_TARGET)
    tls_enabled: bool | None = Field(default=None, description=_TLS)


class DomainReplace(BaseModel):
    """Body of ``PUT /domains/{id}``. Every writable field, always."""

    hostname: Hostname = Field(description=HOSTNAME_DESCRIPTION)
    target_type: DomainTargetType = DomainTargetType.SERVICE
    service_id: uuid.UUID | None = Field(default=None, description=_SERVICE_TARGET)
    deployment_id: uuid.UUID | None = Field(default=None, description=_DEPLOYMENT_TARGET)
    tls_enabled: bool | None = Field(default=None, description=_TLS)

    @model_validator(mode="after")
    def _exactly_one_target(self) -> Self:
        _check_exactly_one_target(self.target_type, self.service_id, self.deployment_id)
        return self


class DomainRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    hostname: str
    environment_id: uuid.UUID
    target_type: DomainTargetType
    service_id: uuid.UUID | None
    deployment_id: uuid.UUID | None
    is_system: bool = Field(
        description="True for the auto-generated {service}.{env}.{base_domain}. "
        "System domains are managed by the control plane and are read-only here."
    )
    tls_enabled: bool
    created_at: datetime
