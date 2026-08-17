"""Environment endpoints.

Created and listed under their project, addressed by id at the top level.
"""

# TODO(auth): protect with get_current_user

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from sqlmodel import Session

from rudder_cp.db import get_session
from rudder_cp.schemas.common import error_responses, translate_errors
from rudder_cp.schemas.environment import (
    EnvironmentCreate,
    EnvironmentRead,
    EnvironmentReplace,
    EnvironmentUpdate,
)
from rudder_cp.services import environments as environment_ops

router = APIRouter(tags=["environments"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.post(
    "/projects/{project_id}/environments",
    status_code=status.HTTP_201_CREATED,
    response_model=EnvironmentRead,
    responses=error_responses(404, 409, 422),
    operation_id="create_environment",
    summary="Create an environment in a project",
    description=(
        "Allocates a dedicated /24 for the environment's WireGuard mesh at "
        "create time — it is never assigned later, because renumbering an "
        "existing mesh is not an option."
    ),
)
async def create_environment(
    project_id: UUID, payload: EnvironmentCreate, session: SessionDep
) -> EnvironmentRead:
    with translate_errors():
        environment = await environment_ops.create_environment(session, project_id, payload)
    return EnvironmentRead.model_validate(environment)


@router.get(
    "/projects/{project_id}/environments",
    response_model=list[EnvironmentRead],
    responses=error_responses(404, 422),
    operation_id="list_environments",
    summary="List a project's environments",
)
async def list_environments(project_id: UUID, session: SessionDep) -> list[EnvironmentRead]:
    with translate_errors():
        rows = await environment_ops.list_environments(session, project_id)
    return [EnvironmentRead.model_validate(row) for row in rows]


@router.get(
    "/environments/{environment_id}",
    response_model=EnvironmentRead,
    responses=error_responses(404, 422),
    operation_id="get_environment",
    summary="Get an environment",
)
async def get_environment(environment_id: UUID, session: SessionDep) -> EnvironmentRead:
    with translate_errors():
        environment = await environment_ops.get_environment(session, environment_id)
    return EnvironmentRead.model_validate(environment)


@router.patch(
    "/environments/{environment_id}",
    response_model=EnvironmentRead,
    responses=error_responses(404, 409, 422),
    operation_id="update_environment",
    summary="Partially update an environment",
    description=(
        "Renaming rewrites the system hostname of every service in this "
        "environment, since the environment name is a label in "
        "`{service}.{environment}.{base_domain}`."
    ),
)
async def update_environment(
    environment_id: UUID, payload: EnvironmentUpdate, session: SessionDep
) -> EnvironmentRead:
    with translate_errors():
        environment = await environment_ops.update_environment(session, environment_id, payload)
    return EnvironmentRead.model_validate(environment)


@router.put(
    "/environments/{environment_id}",
    response_model=EnvironmentRead,
    responses=error_responses(404, 409, 422),
    operation_id="replace_environment",
    summary="Replace an environment",
    description="Sets every writable field. Idempotent.",
)
async def replace_environment(
    environment_id: UUID, payload: EnvironmentReplace, session: SessionDep
) -> EnvironmentRead:
    with translate_errors():
        environment = await environment_ops.replace_environment(session, environment_id, payload)
    return EnvironmentRead.model_validate(environment)


@router.delete(
    "/environments/{environment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=error_responses(404, 422, 503),
    operation_id="delete_environment",
    summary="Delete an environment and everything in it",
    description="Cascades to services, domains, variables, volumes and deployments.",
)
async def delete_environment(environment_id: UUID, request: Request, session: SessionDep) -> None:
    with translate_errors():
        settings = request.app.state.settings
        await environment_ops.delete_environment(
            session,
            environment_id,
            agent=request.app.state.agent,
            settings=settings,
        )
