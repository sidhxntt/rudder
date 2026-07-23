"""Service endpoints.

Created and listed under their environment, addressed by id at the top level.
Deploying a service is a different workstream and does not live here.
"""

# TODO(auth): protect with get_current_user

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from sqlmodel import Session

from rudder_cp.db import get_session
from rudder_cp.schemas.common import error_responses, translate_errors
from rudder_cp.schemas.domain import DomainRead
from rudder_cp.schemas.service import (
    ServiceCreate,
    ServiceRead,
    ServiceReplace,
    ServiceUpdate,
)
from rudder_cp.services import domains as domain_ops
from rudder_cp.services import services as service_ops

router = APIRouter(tags=["services"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.post(
    "/environments/{environment_id}/services",
    status_code=status.HTTP_201_CREATED,
    response_model=ServiceRead,
    responses=error_responses(404, 409, 422),
    operation_id="create_service",
    summary="Create a service in an environment",
    description=(
        "Also creates the service's system domain at "
        "`{name}.{environment}.{base_domain}` (D15). If that hostname is "
        "already taken the whole create fails with 409."
    ),
)
async def create_service(
    environment_id: UUID, payload: ServiceCreate, session: SessionDep
) -> ServiceRead:
    with translate_errors():
        service = await service_ops.create_service(session, environment_id, payload)
    return ServiceRead.model_validate(service)


@router.get(
    "/environments/{environment_id}/services",
    response_model=list[ServiceRead],
    responses=error_responses(404, 422),
    operation_id="list_services",
    summary="List an environment's services",
)
async def list_services(environment_id: UUID, session: SessionDep) -> list[ServiceRead]:
    with translate_errors():
        rows = await service_ops.list_services(session, environment_id)
    return [ServiceRead.model_validate(row) for row in rows]


@router.get(
    "/services/{service_id}",
    response_model=ServiceRead,
    responses=error_responses(404, 422),
    operation_id="get_service",
    summary="Get a service",
)
async def get_service(service_id: UUID, session: SessionDep) -> ServiceRead:
    with translate_errors():
        service = await service_ops.get_service(session, service_id)
    return ServiceRead.model_validate(service)


@router.patch(
    "/services/{service_id}",
    response_model=ServiceRead,
    responses=error_responses(404, 409, 422),
    operation_id="update_service",
    summary="Partially update a service",
    description=(
        "Fields left out are untouched. Renaming rewrites the system domain "
        "hostname. `canvas_x` / `canvas_y` are UI metadata (D6): they persist "
        "and trigger nothing."
    ),
)
async def update_service(
    service_id: UUID, payload: ServiceUpdate, session: SessionDep
) -> ServiceRead:
    with translate_errors():
        service = await service_ops.update_service(session, service_id, payload)
    return ServiceRead.model_validate(service)


@router.put(
    "/services/{service_id}",
    response_model=ServiceRead,
    responses=error_responses(404, 409, 422),
    operation_id="replace_service",
    summary="Replace a service",
    description=(
        "Sets every writable field, resetting anything omitted to its default. "
        "Idempotent: the same body twice yields the same resource."
    ),
)
async def replace_service(
    service_id: UUID, payload: ServiceReplace, session: SessionDep
) -> ServiceRead:
    with translate_errors():
        service = await service_ops.replace_service(session, service_id, payload)
    return ServiceRead.model_validate(service)


@router.delete(
    "/services/{service_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=error_responses(404, 422, 503),
    operation_id="delete_service",
    summary="Delete a service and everything in it",
    description=(
        "Cascades to its system domain, any domain targeting it or one of its "
        "deployments, its variables, volumes, deployments and instances."
    ),
)
async def delete_service(service_id: UUID, request: Request, session: SessionDep) -> None:
    with translate_errors():
        settings = request.app.state.settings
        await service_ops.delete_service(
            session,
            service_id,
            agent=request.app.state.agent,
            settings=settings,
        )


@router.get(
    "/services/{service_id}/domains",
    response_model=list[DomainRead],
    responses=error_responses(404, 422),
    operation_id="list_service_domains",
    summary="List every hostname that resolves to a service",
)
async def list_service_domains(service_id: UUID, session: SessionDep) -> list[DomainRead]:
    with translate_errors():
        rows = await domain_ops.list_domains_for_service(session, service_id)
    return [DomainRead.model_validate(row) for row in rows]
