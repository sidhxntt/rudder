"""Domain logic for environments.

Kubernetes namespaces and NetworkPolicies are the environment-isolation
boundary.  The previous WireGuard CIDR allocator was removed in Phase 4.

Takes ``Session`` as an argument. Never imports FastAPI.
"""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from rudder_cp.config import Settings
from rudder_cp.models import Environment, Project, Service
from rudder_cp.schemas.common import (
    ConflictError,
    NotFoundError,
    RudderError,
)
from rudder_cp.schemas.environment import (
    EnvironmentCreate,
    EnvironmentReplace,
    EnvironmentUpdate,
)
from rudder_cp.services import domains, services, traefik
from rudder_cp.services.agent_client import AgentClient

ENVIRONMENT_NAME_TAKEN = "environment_name_taken"


async def list_environments(session: Session, project_id: uuid.UUID) -> list[Environment]:
    project = _require_project(session, project_id)
    rows = session.exec(
        select(Environment)
        .where(Environment.project_id == project.id)
        .order_by(Environment.name)
    ).all()
    return list(rows)


async def get_environment(session: Session, environment_id: uuid.UUID) -> Environment:
    return _require_environment(session, environment_id)


async def create_environment(
    session: Session, project_id: uuid.UUID, payload: EnvironmentCreate
) -> Environment:
    project = _require_project(session, project_id)
    environment = await create_environment_row(session, project=project, payload=payload)
    session.commit()
    session.refresh(environment)
    return environment


async def create_environment_row(
    session: Session, *, project: Project, payload: EnvironmentCreate
) -> Environment:
    """Insert an environment. Does not commit.

    Split out so project creation can make a project and its ``production``
    environment in one transaction.
    """
    environment = Environment(
        project_id=project.id,
        name=payload.name,
        is_production=payload.is_production,
    )
    session.add(environment)
    _flush_or_conflict(session, project_id=project.id, name=environment.name)
    return environment


async def update_environment(
    session: Session, environment_id: uuid.UUID, payload: EnvironmentUpdate
) -> Environment:
    environment = _require_environment(session, environment_id)
    data = payload.model_dump(exclude_unset=True)
    return await _apply_environment_write(session, environment=environment, data=data)


async def replace_environment(
    session: Session, environment_id: uuid.UUID, payload: EnvironmentReplace
) -> Environment:
    """PUT. All writable environment fields are replaced."""
    environment = _require_environment(session, environment_id)
    return await _apply_environment_write(
        session, environment=environment, data=payload.model_dump()
    )


async def delete_environment(
    session: Session, environment_id: uuid.UUID, *, agent: AgentClient, settings: Settings
) -> None:
    """Delete an environment and everything inside it. See ``purge_environment``."""
    environment = _require_environment(session, environment_id)
    service_ids = list(
        session.exec(select(Service.id).where(Service.environment_id == environment.id)).all()
    )
    await services.remove_runtime_containers(
        session, service_ids=service_ids, agent=agent, settings=settings
    )
    await purge_environment(session, environment)
    session.commit()
    await traefik.render_all(session, settings)


async def purge_environment(session: Session, environment: Environment) -> None:
    """Delete one environment's rows. Does not commit — the caller owns the txn."""
    await services.purge_services_in_environment(session, environment)
    # Sweep any domain that outlived its target — user domains attached to the
    # environment rather than to a service that was in it.
    await domains.delete_domains_for_environment(session, environment_id=environment.id)
    session.delete(environment)
    session.flush()


async def _apply_environment_write(
    session: Session, *, environment: Environment, data: dict[str, object]
) -> Environment:
    renamed = "name" in data and data["name"] != environment.name

    for field, value in data.items():
        setattr(environment, field, value)

    session.add(environment)
    _flush_or_conflict(session, project_id=environment.project_id, name=environment.name)

    if renamed:
        # Every system hostname in this environment embeds the env name.
        try:
            await services.sync_system_domains_for_environment(session, environment)
        except RudderError:
            session.rollback()
            raise

    session.commit()
    session.refresh(environment)
    return environment


def _flush_or_conflict(session: Session, *, project_id: uuid.UUID, name: str) -> None:
    """uq_environment_project_name must surface as a 409, never a 500."""
    try:
        session.flush()
    except IntegrityError as err:
        session.rollback()
        raise ConflictError(
            f"an environment named '{name}' already exists in this project",
            code=ENVIRONMENT_NAME_TAKEN,
            details={"project_id": str(project_id), "name": name},
        ) from err


def _require_project(session: Session, project_id: uuid.UUID) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError(
            f"project {project_id} does not exist",
            details={"project_id": str(project_id)},
        )
    return project


def _require_environment(session: Session, environment_id: uuid.UUID) -> Environment:
    environment = session.get(Environment, environment_id)
    if environment is None:
        raise NotFoundError(
            f"environment {environment_id} does not exist",
            details={"environment_id": str(environment_id)},
        )
    return environment
