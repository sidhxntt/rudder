"""Project endpoints.

Nesting convention, applied consistently across this API: **create and list
under the parent, address by id at the top level.** So a project's
environments are created at ``POST /projects/{id}/environments`` (in
``routers/environments.py``) and then addressed at ``GET /environments/{id}``.

Routers parse, call exactly one service function, and serialise. All logic is
in ``services/``.
"""

# TODO(auth): protect with get_current_user

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from sqlmodel import Session

from rudder_cp.db import get_session
from rudder_cp.routers.auth import CurrentUser
from rudder_cp.schemas.common import error_responses, translate_errors
from rudder_cp.schemas.project import (
    ProjectCreate,
    ProjectRead,
    ProjectReplace,
    ProjectUpdate,
)
from rudder_cp.services import projects as project_ops
from rudder_cp.services.ownership import list_owned_projects, require_owned_project

router = APIRouter(tags=["projects"])

SessionDep = Annotated[Session, Depends(get_session)]


@router.post(
    "/projects",
    status_code=status.HTTP_201_CREATED,
    response_model=ProjectRead,
    responses=error_responses(409, 422),
    operation_id="create_project",
    summary="Create a project",
    description=(
        "Creates the project and its `production` environment. Returns the "
        "full project resource."
    ),
)
async def create_project(
    payload: ProjectCreate, session: SessionDep, user: CurrentUser
) -> ProjectRead:
    with translate_errors():
        project = await project_ops.create_project(session, payload, owner_id=user.id)
    return ProjectRead.model_validate(project)


@router.get(
    "/projects",
    response_model=list[ProjectRead],
    responses=error_responses(422),
    operation_id="list_projects",
    summary="List projects",
)
async def list_projects(session: SessionDep, user: CurrentUser) -> list[ProjectRead]:
    with translate_errors():
        projects = list_owned_projects(session, user.id)
    return [ProjectRead.model_validate(project) for project in projects]


@router.get(
    "/projects/{project_id}",
    response_model=ProjectRead,
    responses=error_responses(404, 422),
    operation_id="get_project",
    summary="Get a project",
)
async def get_project(project_id: UUID, session: SessionDep, user: CurrentUser) -> ProjectRead:
    with translate_errors():
        project = require_owned_project(session, project_id, user.id)
    return ProjectRead.model_validate(project)


@router.patch(
    "/projects/{project_id}",
    response_model=ProjectRead,
    responses=error_responses(404, 409, 422),
    operation_id="update_project",
    summary="Partially update a project",
    description="Fields left out are untouched. Returns the full project resource.",
)
async def update_project(
    project_id: UUID, payload: ProjectUpdate, session: SessionDep, user: CurrentUser
) -> ProjectRead:
    with translate_errors():
        require_owned_project(session, project_id, user.id)
        project = await project_ops.update_project(session, project_id, payload)
    return ProjectRead.model_validate(project)


@router.put(
    "/projects/{project_id}",
    response_model=ProjectRead,
    responses=error_responses(404, 409, 422),
    operation_id="replace_project",
    summary="Replace a project",
    description=(
        "Sets every writable field. Idempotent: the same body twice yields the "
        "same resource."
    ),
)
async def replace_project(
    project_id: UUID, payload: ProjectReplace, session: SessionDep, user: CurrentUser
) -> ProjectRead:
    with translate_errors():
        require_owned_project(session, project_id, user.id)
        project = await project_ops.replace_project(session, project_id, payload)
    return ProjectRead.model_validate(project)


@router.delete(
    "/projects/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=error_responses(404, 422, 503),
    operation_id="delete_project",
    summary="Delete a project and everything in it",
    description=(
        "Cascades to environments, services, domains, variables, volumes, "
        "deployments and instances. No body: the resource is gone, so there is "
        "nothing left to cache."
    ),
)
async def delete_project(
    project_id: UUID, request: Request, session: SessionDep, user: CurrentUser
) -> None:
    with translate_errors():
        require_owned_project(session, project_id, user.id)
        await project_ops.delete_project(
            session,
            project_id,
            agent=request.app.state.agent,
            settings=request.app.state.settings,
        )
