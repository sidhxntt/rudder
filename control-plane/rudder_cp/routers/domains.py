"""Domain endpoints — D15.

Created and listed under their environment, addressed by id at the top level.

System domains (``is_system=true``) are visible here but not writable: they are
created, renamed and deleted with their service. Attempting to create one, or
to mutate or delete an existing one, is refused with 403
``system_domain_immutable``.
"""

# TODO(auth): protect with get_current_user

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from sqlmodel import Session

from rudder_cp.db import get_session
from rudder_cp.routers.auth import CurrentUser
from rudder_cp.schemas.common import error_responses, translate_errors
from rudder_cp.schemas.domain import DomainCreate, DomainRead, DomainReplace, DomainUpdate
from rudder_cp.services import domains as domain_ops
from rudder_cp.services.ownership import require_owned_domain, require_owned_environment

router = APIRouter(tags=["domains"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.post(
    "/environments/{environment_id}/domains",
    status_code=status.HTTP_201_CREATED,
    response_model=DomainRead,
    responses=error_responses(404, 409, 422),
    operation_id="create_domain",
    summary="Create a domain in an environment",
    description=(
        "Exactly one of `service_id` / `deployment_id` must be set, matching "
        "`target_type`; anything else is a 422. A hostname already in use — "
        "including by a system domain — is a 409. The created domain is never "
        "a system domain."
    ),
)
async def create_domain(
    environment_id: UUID, payload: DomainCreate, session: SessionDep, user: CurrentUser
) -> DomainRead:
    with translate_errors():
        require_owned_environment(session, environment_id, user.id)
        domain = await domain_ops.create_domain(session, environment_id, payload)
    return DomainRead.model_validate(domain)


@router.get(
    "/environments/{environment_id}/domains",
    response_model=list[DomainRead],
    responses=error_responses(404, 422),
    operation_id="list_domains",
    summary="List an environment's domains",
)
async def list_domains(
    environment_id: UUID, session: SessionDep, user: CurrentUser
) -> list[DomainRead]:
    with translate_errors():
        require_owned_environment(session, environment_id, user.id)
        rows = await domain_ops.list_domains(session, environment_id)
    return [DomainRead.model_validate(row) for row in rows]


@router.get(
    "/domains/{domain_id}",
    response_model=DomainRead,
    responses=error_responses(404, 422),
    operation_id="get_domain",
    summary="Get a domain",
)
async def get_domain(domain_id: UUID, session: SessionDep, user: CurrentUser) -> DomainRead:
    with translate_errors():
        domain = require_owned_domain(session, domain_id, user.id)
    return DomainRead.model_validate(domain)


@router.patch(
    "/domains/{domain_id}",
    response_model=DomainRead,
    responses=error_responses(403, 404, 409, 422),
    operation_id="update_domain",
    summary="Partially update a domain",
    description=(
        "Retargeting a domain is the rollback primitive: an UPDATE, not a "
        "rebuild. Send `target_type` together with the id it requires. "
        "Refused with 403 on a system domain."
    ),
)
async def update_domain(
    domain_id: UUID, payload: DomainUpdate, session: SessionDep, user: CurrentUser
) -> DomainRead:
    with translate_errors():
        require_owned_domain(session, domain_id, user.id)
        domain = await domain_ops.update_domain(session, domain_id, payload)
    return DomainRead.model_validate(domain)


@router.put(
    "/domains/{domain_id}",
    response_model=DomainRead,
    responses=error_responses(403, 404, 409, 422),
    operation_id="replace_domain",
    summary="Replace a domain",
    description="Sets every writable field. Idempotent. Refused with 403 on a system domain.",
)
async def replace_domain(
    domain_id: UUID, payload: DomainReplace, session: SessionDep, user: CurrentUser
) -> DomainRead:
    with translate_errors():
        require_owned_domain(session, domain_id, user.id)
        domain = await domain_ops.replace_domain(session, domain_id, payload)
    return DomainRead.model_validate(domain)


@router.delete(
    "/domains/{domain_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=error_responses(403, 404, 422),
    operation_id="delete_domain",
    summary="Delete a domain",
    description=(
        "Refused with 403 on a system domain — delete the service instead, "
        "which takes its system domain with it."
    ),
)
async def delete_domain(domain_id: UUID, session: SessionDep, user: CurrentUser) -> None:
    with translate_errors():
        require_owned_domain(session, domain_id, user.id)
        await domain_ops.delete_domain(session, domain_id)
