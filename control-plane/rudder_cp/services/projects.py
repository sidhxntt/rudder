"""Domain logic for Projects.

Creating a project also creates its ``production`` environment. Every phase
document assumes it exists (``curl -H "Host: api.production.localhost"``), a
project with no environment cannot hold a service, and making the client issue
a second call to reach a usable state would be a worse API. The environment is
an ordinary row — it can be renamed or deleted like any other.

Takes ``Session`` as an argument. Never imports FastAPI.
"""

import uuid
from typing import Final

from sqlmodel import Session, select

from rudder_cp.models import Project, User
from rudder_cp.schemas.common import ConflictError, NotFoundError
from rudder_cp.schemas.environment import EnvironmentCreate
from rudder_cp.schemas.project import ProjectCreate, ProjectReplace, ProjectUpdate
from rudder_cp.services import environments

#: The environment every project starts with.
DEFAULT_ENVIRONMENT_NAME: Final[str] = "production"

NO_OWNER = "no_owner"


async def list_projects(session: Session) -> list[Project]:
    rows = session.exec(select(Project).order_by(Project.created_at)).all()
    return list(rows)


async def get_project(session: Session, project_id: uuid.UUID) -> Project:
    return _require_project(session, project_id)


async def create_project(
    session: Session, payload: ProjectCreate, *, owner_id: uuid.UUID | None = None
) -> Project:
    """Create a project and its ``production`` environment in one transaction.

    ``owner_id`` is a parameter rather than something read from a request:
    when auth lands, the router passes the authenticated user's id and nothing
    else changes. Until then it falls back to the single seeded user, because
    Rudder is single-tenant by design and there is exactly one.
    """
    resolved_owner = owner_id if owner_id is not None else await default_owner_id(session)

    project = Project(name=payload.name, owner_id=resolved_owner)
    session.add(project)
    session.flush()

    await environments.create_environment_row(
        session,
        project=project,
        payload=EnvironmentCreate(name=DEFAULT_ENVIRONMENT_NAME, is_production=True),
    )

    session.commit()
    session.refresh(project)
    return project


async def update_project(
    session: Session, project_id: uuid.UUID, payload: ProjectUpdate
) -> Project:
    project = _require_project(session, project_id)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


async def replace_project(
    session: Session, project_id: uuid.UUID, payload: ProjectReplace
) -> Project:
    project = _require_project(session, project_id)
    project.name = payload.name
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


async def delete_project(session: Session, project_id: uuid.UUID) -> None:
    """Delete a project, its environments, and everything inside them.

    Cascade rather than refuse-if-not-empty: every project has at least one
    environment from the moment it is created, so a refusal would make
    ``DELETE /projects/{id}`` unusable without a teardown ritual. The
    alternative — deleting the project and leaving its children — is the one
    outcome that must never happen.
    """
    project = _require_project(session, project_id)
    for environment in await environments.list_environments(session, project.id):
        await environments.purge_environment(session, environment)
    session.delete(project)
    session.commit()


async def default_owner_id(session: Session) -> uuid.UUID:
    """The single seeded user. Placeholder until ``get_current_user`` exists."""
    user = session.exec(select(User).order_by(User.created_at)).first()
    if user is None:
        raise ConflictError(
            "no user has been seeded yet; the control plane seeds one on first boot",
            code=NO_OWNER,
        )
    return user.id


def _require_project(session: Session, project_id: uuid.UUID) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError(
            f"project {project_id} does not exist",
            details={"project_id": str(project_id)},
        )
    return project
