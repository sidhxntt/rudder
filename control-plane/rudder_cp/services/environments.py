"""Domain logic for Environments, including WireGuard subnet allocation.

``wg_subnet`` is allocated at create time even though nothing reads it before
Phase 3. That is not speculative — an environment that exists without a subnet
cannot be given one later without renumbering every peer in it, so the cheap
moment to allocate is the only moment.

Takes ``Session`` as an argument. Never imports FastAPI.
"""

import uuid
from ipaddress import IPv4Network
from typing import Final

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from rudder_cp.models import Environment, Project
from rudder_cp.schemas.common import (
    ConflictError,
    NotFoundError,
    ResourceExhaustedError,
    RudderError,
)
from rudder_cp.schemas.environment import (
    EnvironmentCreate,
    EnvironmentReplace,
    EnvironmentUpdate,
)
from rudder_cp.services import domains, services

ENVIRONMENT_NAME_TAKEN = "environment_name_taken"
SUBNET_POOL_EXHAUSTED = "wg_subnet_pool_exhausted"

#: One /24 per environment out of a single RFC 1918 /16. 10.42.0.0/16 is picked
#: to sit well clear of the 10.0.x and 172.17.x ranges Docker hands out by
#: default, so the mesh does not collide with bridge networks in Phase 3.
WG_SUPERNET: Final[IPv4Network] = IPv4Network("10.42.0.0/16")
WG_PREFIX_LENGTH: Final[int] = 24

#: Postgres advisory-lock key for the subnet allocator. Arbitrary but fixed;
#: it only has to be distinct from the deploy path's ``service_id`` keys (D11).
WG_ALLOCATOR_LOCK_KEY: Final[int] = 0x5255_4457_0001


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
    """Insert an environment with an allocated subnet. Does not commit.

    Split out so project creation can make a project and its ``production``
    environment in one transaction.
    """
    environment = Environment(
        project_id=project.id,
        name=payload.name,
        is_production=payload.is_production,
        wg_subnet=await allocate_wg_subnet(session),
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
    """PUT. ``wg_subnet`` is server-owned and survives a replace untouched."""
    environment = _require_environment(session, environment_id)
    return await _apply_environment_write(
        session, environment=environment, data=payload.model_dump()
    )


async def delete_environment(session: Session, environment_id: uuid.UUID) -> None:
    """Delete an environment and everything inside it. See ``purge_environment``."""
    environment = _require_environment(session, environment_id)
    await purge_environment(session, environment)
    session.commit()


async def purge_environment(session: Session, environment: Environment) -> None:
    """Delete one environment's rows. Does not commit — the caller owns the txn."""
    await services.purge_services_in_environment(session, environment)
    # Sweep any domain that outlived its target — user domains attached to the
    # environment rather than to a service that was in it.
    await domains.delete_domains_for_environment(session, environment_id=environment.id)
    session.delete(environment)
    session.flush()


async def allocate_wg_subnet(session: Session) -> str:
    """Hand out the lowest free /24 in ``WG_SUPERNET``.

    Concurrency: the environment table has no unique index on ``wg_subnet``, so
    read-then-insert is not safe on its own — two concurrent creates would both
    read the same set of taken subnets and both pick the same one. A Postgres
    transaction-scoped advisory lock serialises the read-and-insert window; it
    is released automatically when the caller commits or rolls back, so no
    cleanup path can leak it. This mirrors D11, which already uses advisory
    locks for the deploy path.

    On SQLite (tests) the lock is skipped: writers are serialised by the
    database itself.
    """
    _lock_allocator(session)
    taken = {
        subnet
        for subnet in session.exec(select(Environment.wg_subnet)).all()
        if subnet is not None
    }
    for candidate in WG_SUPERNET.subnets(new_prefix=WG_PREFIX_LENGTH):
        text = str(candidate)
        if text not in taken:
            return text
    raise ResourceExhaustedError(
        f"no free /{WG_PREFIX_LENGTH} left in {WG_SUPERNET}",
        code=SUBNET_POOL_EXHAUSTED,
        details={"supernet": str(WG_SUPERNET), "allocated": len(taken)},
    )


# --------------------------------------------------------------------------
# Internals.
# --------------------------------------------------------------------------


def _lock_allocator(session: Session) -> None:
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    session.execute(
        sa.text("SELECT pg_advisory_xact_lock(:key)"), {"key": WG_ALLOCATOR_LOCK_KEY}
    )


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
