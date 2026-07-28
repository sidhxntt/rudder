"""Domain logic for Services.

Two things here are load-bearing beyond plain CRUD:

* **D15.** Creating a service creates its system Domain in the same
  transaction; renaming a service rewrites that hostname; deleting a service
  deletes it. A service without a URL, or a URL that outlives its service, is a
  bug in this file.
* **D6.** ``canvas_x`` / ``canvas_y`` are UI metadata. They are writable and
  they are inert — nothing in this module reacts to them.

Takes ``Session`` as an argument. Never imports FastAPI.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from rudder_cp.config import Settings
from rudder_cp.models import (
    Deployment,
    Environment,
    Instance,
    InstanceStatus,
    Project,
    Service,
    ServiceManagedCapabilities,
    ServiceOperation,
    Variable,
    Volume,
)
from rudder_cp.schemas.common import ConflictError, NotFoundError, RudderError
from rudder_cp.schemas.service import ServiceCreate, ServiceReplace, ServiceUpdate
from rudder_cp.services import domains, traefik
from rudder_cp.services.agent_client import AgentClient, AgentError

SERVICE_NAME_TAKEN = "service_name_taken"


class RuntimeCleanupError(RudderError):
    """The runtime must be reachable before deleting its service records."""

    status_code = 503

    def __init__(self, *, container_id: str, reason: str) -> None:
        super().__init__(
            f"Could not remove runtime container {container_id}. {reason}",
            code="runtime_cleanup_failed",
            details={"container_id": container_id},
        )


async def list_services(
    session: Session, environment_id: uuid.UUID, *, owner_id: uuid.UUID | None = None
) -> list[Service]:
    environment = _require_environment(session, environment_id, owner_id=owner_id)
    rows = session.exec(
        select(Service).where(Service.environment_id == environment.id).order_by(Service.name)
    ).all()
    return list(rows)


async def get_service(
    session: Session, service_id: uuid.UUID, *, owner_id: uuid.UUID | None = None
) -> Service:
    return _require_service(session, service_id, owner_id=owner_id)


async def create_service(
    session: Session,
    environment_id: uuid.UUID,
    payload: ServiceCreate,
    *,
    owner_id: uuid.UUID | None = None,
) -> Service:
    """Create a service and, in the same transaction, its D15 system Domain."""
    environment = _require_environment(session, environment_id, owner_id=owner_id)

    service = Service(environment_id=environment.id, **payload.model_dump())
    session.add(service)
    _flush_or_conflict(session, environment_id=environment.id, name=service.name)

    try:
        await domains.create_system_domain(session, environment=environment, service=service)
    except RudderError:
        # A service with no URL is not a service. If its hostname is taken the
        # whole create fails rather than half-landing.
        session.rollback()
        raise

    session.commit()
    session.refresh(service)
    return service


async def update_service(
    session: Session,
    service_id: uuid.UUID,
    payload: ServiceUpdate,
    *,
    owner_id: uuid.UUID | None = None,
) -> Service:
    """PATCH. Absent fields are untouched; ``None`` is only sent for nullables."""
    service = _require_service(session, service_id, owner_id=owner_id)
    data = payload.model_dump(exclude_unset=True)
    return await _apply_service_write(session, service=service, data=data)


async def replace_service(
    session: Session,
    service_id: uuid.UUID,
    payload: ServiceReplace,
    *,
    owner_id: uuid.UUID | None = None,
) -> Service:
    """PUT. Every writable field is set, so the same body twice is the same row."""
    service = _require_service(session, service_id, owner_id=owner_id)
    return await _apply_service_write(session, service=service, data=payload.model_dump())


async def delete_service(
    session: Session,
    service_id: uuid.UUID,
    *,
    agent: AgentClient,
    settings: Settings,
    owner_id: uuid.UUID | None = None,
) -> None:
    """Delete a service and everything that hangs off it.

    Cascade, not refuse: the FKs in the schema have no ON DELETE rule, so a
    refusal would leave the user unable to delete a service at all without
    hand-deleting its variables, volumes, deployments and domains first.
    """
    service = _require_service(session, service_id, owner_id=owner_id)
    await remove_runtime_containers(
        session, service_ids=[service.id], agent=agent, settings=settings
    )
    await purge_service(session, service)
    session.commit()
    await traefik.render_all(session, settings)


async def remove_runtime_containers(
    session: Session,
    *,
    service_ids: list[uuid.UUID],
    agent: AgentClient,
    settings: Settings,
) -> None:
    """Remove every runtime container owned by the supplied services.

    The agent's delete operation is idempotent, so this includes rows marked
    stopped as well as active ones: a stale runtime can never survive a
    successful service/environment deletion.  It runs before database cleanup;
    an agent failure leaves the service and its routes intact for a retry.
    """
    if not service_ids:
        return
    instances = session.exec(
        select(Instance)
        .join(Deployment, Deployment.id == Instance.deployment_id)  # type: ignore[arg-type]
        .where(Deployment.service_id.in_(service_ids))  # type: ignore[attr-defined]
    ).all()
    for instance in instances:
        if instance.container_id:
            try:
                await agent.remove(instance.container_id, drain_seconds=0)
            except AgentError as exc:
                # Previous removals in this loop are already real. Persist
                # their stopped state and remove them from Traefik before
                # returning the error, so no route keeps targeting a dead
                # container while the user retries deletion.
                session.commit()
                await traefik.render_all(session, settings)
                raise RuntimeCleanupError(
                    container_id=instance.container_id, reason=str(exc)
                ) from exc
            instance.status = InstanceStatus.STOPPED
            instance.stopped_at = datetime.now(UTC)
            session.add(instance)


async def purge_service(session: Session, service: Service) -> None:
    """Delete one service's rows. Does not commit — the caller owns the txn.

    Order matters: domains first (they reference the service and its
    deployments), then instances, then deployments, then the service's own
    children.

    Runtime teardown belongs to ``delete_service`` / ``delete_environment``;
    this helper remains database-only so it can participate in larger
    transactions such as project deletion.
    """
    deployment_ids = list(
        session.exec(select(Deployment.id).where(Deployment.service_id == service.id)).all()
    )
    await domains.delete_domains_for_service(
        session, service_id=service.id, deployment_ids=deployment_ids
    )

    if deployment_ids:
        instances = session.exec(
            select(Instance).where(Instance.deployment_id.in_(deployment_ids))  # type: ignore[attr-defined]
        ).all()
        for instance in instances:
            session.delete(instance)

    for deployment in session.exec(
        select(Deployment).where(Deployment.service_id == service.id)
    ).all():
        session.delete(deployment)

    for variable in session.exec(
        select(Variable).where(Variable.service_id == service.id)
    ).all():
        session.delete(variable)

    for volume in session.exec(select(Volume).where(Volume.service_id == service.id)).all():
        session.delete(volume)

    # ServiceOperation deliberately has no database ON DELETE cascade: an
    # operation audit cannot outlive the service it describes, and explicit
    # deletion keeps SQLite and PostgreSQL teardown ordering identical.
    for operation in session.exec(
        select(ServiceOperation).where(ServiceOperation.service_id == service.id)
    ).all():
        session.delete(operation)

    # Trusted import/template capability metadata is also service-owned.  It
    # intentionally has no database cascade so SQLite and PostgreSQL follow
    # the same explicit, FK-safe teardown order.
    for capabilities in session.exec(
        select(ServiceManagedCapabilities).where(
            ServiceManagedCapabilities.service_id == service.id
        )
    ).all():
        session.delete(capabilities)

    # These service children have no database-level ON DELETE cascade. Flush
    # their deletion before deleting the parent, otherwise SQLAlchemy can order
    # statements incorrectly and the transaction fails on the FK.
    session.flush()
    session.delete(service)
    session.flush()


async def purge_services_in_environment(session: Session, environment: Environment) -> None:
    """Cascade helper for environment deletion. Does not commit."""
    rows = session.exec(
        select(Service).where(Service.environment_id == environment.id)
    ).all()
    for service in rows:
        await purge_service(session, service)


async def sync_system_domains_for_environment(
    session: Session, environment: Environment
) -> None:
    """Rewrite every system hostname in an environment after it was renamed."""
    rows = session.exec(
        select(Service).where(Service.environment_id == environment.id)
    ).all()
    for service in rows:
        await domains.rename_system_domain(session, environment=environment, service=service)


# --------------------------------------------------------------------------
# Internals.
# --------------------------------------------------------------------------


async def _apply_service_write(
    session: Session, *, service: Service, data: dict[str, object]
) -> Service:
    environment = _require_environment(session, service.environment_id)
    renamed = "name" in data and data["name"] != service.name

    for field, value in data.items():
        # canvas_x / canvas_y land here like any other column. D6: they are UI
        # metadata, so this write is deliberately not a deploy trigger and not
        # a reconciliation trigger.
        setattr(service, field, value)

    session.add(service)
    _flush_or_conflict(session, environment_id=service.environment_id, name=service.name)

    if renamed:
        try:
            await domains.rename_system_domain(
                session, environment=environment, service=service
            )
        except RudderError:
            session.rollback()
            raise

    session.commit()
    session.refresh(service)
    return service


def _flush_or_conflict(session: Session, *, environment_id: uuid.UUID, name: str) -> None:
    """uq_service_environment_name must surface as a 409, never a 500."""
    try:
        session.flush()
    except IntegrityError as err:
        session.rollback()
        raise ConflictError(
            f"a service named '{name}' already exists in this environment",
            code=SERVICE_NAME_TAKEN,
            details={"environment_id": str(environment_id), "name": name},
        ) from err


def _require_environment(
    session: Session, environment_id: uuid.UUID, *, owner_id: uuid.UUID | None = None
) -> Environment:
    environment = session.get(Environment, environment_id)
    if environment is None:
        raise NotFoundError(
            f"environment {environment_id} does not exist",
            details={"environment_id": str(environment_id)},
        )
    if owner_id is not None:
        project = session.get(Project, environment.project_id)
        if project is None or project.owner_id != owner_id:
            raise NotFoundError(
                f"environment {environment_id} does not exist",
                details={"environment_id": str(environment_id)},
            )
    return environment


def _require_service(
    session: Session, service_id: uuid.UUID, *, owner_id: uuid.UUID | None = None
) -> Service:
    service = session.get(Service, service_id)
    if service is None:
        raise NotFoundError(
            f"service {service_id} does not exist",
            details={"service_id": str(service_id)},
        )
    if owner_id is not None:
        _require_environment(session, service.environment_id, owner_id=owner_id)
    return service
