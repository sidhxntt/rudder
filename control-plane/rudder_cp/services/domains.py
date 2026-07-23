"""Domain logic for Domains — D15.

The Domain table is the routing unit: Traefik config is generated from Domain
rows, never from Service rows. Two kinds of row live here and they follow
different rules:

* **System domains** (``is_system=True``) are the auto-generated
  ``{service}.{environment}.{base_domain}``. The control plane owns them
  entirely — created with their service, renamed with their service, deleted
  with their service. The public API refuses to create, mutate or delete one.
* **User domains** are everything else: custom hostnames and, from Phase 5,
  immutable per-deployment URLs.

Takes ``Session`` as an argument. Never imports FastAPI.
"""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from rudder_cp.config import get_settings
from rudder_cp.models import Deployment, Domain, DomainTargetType, Environment, Service
from rudder_cp.schemas.common import (
    ConflictError,
    ForbiddenError,
    InvalidRequestError,
    NotFoundError,
)
from rudder_cp.schemas.domain import DomainCreate, DomainReplace, DomainUpdate
from rudder_cp.services.naming import system_hostname

SYSTEM_DOMAIN_IMMUTABLE = "system_domain_immutable"
HOSTNAME_TAKEN = "hostname_taken"


def resolve_tls_enabled(explicit: bool | None) -> bool:
    """D8 — a domain follows ``RUDDER_TLS_MODE`` unless it says otherwise.

    ACME HTTP-01 cannot work against ``*.localhost``, so dev runs with
    ``tls_mode=off`` and every domain it creates is plain HTTP.
    """
    if explicit is not None:
        return explicit
    return get_settings().tls_mode == "acme"


# --------------------------------------------------------------------------
# System domains. Called by services.services, not by any router.
# --------------------------------------------------------------------------


async def create_system_domain(
    session: Session, *, environment: Environment, service: Service
) -> Domain:
    """Insert the D15 system domain for a freshly created service.

    Flushes but does not commit — the caller owns the transaction so that a
    hostname collision aborts the whole service create rather than leaving a
    service with no URL.
    """
    hostname = system_hostname(service.name, environment.name, get_settings().base_domain)
    _require_hostname_free(session, hostname)
    domain = Domain(
        hostname=hostname,
        environment_id=environment.id,
        target_type=DomainTargetType.SERVICE,
        service_id=service.id,
        deployment_id=None,
        is_system=True,
        tls_enabled=resolve_tls_enabled(None),
    )
    session.add(domain)
    _flush_or_conflict(session, hostname)
    return domain


async def rename_system_domain(
    session: Session, *, environment: Environment, service: Service
) -> None:
    """Recompute a service's system hostname after a service or env rename.

    Without this the hostname silently keeps the old name and Traefik keeps
    routing a URL the user can no longer see in the API.
    """
    hostname = system_hostname(service.name, environment.name, get_settings().base_domain)
    for domain in _system_domains_for_service(session, service.id):
        if domain.hostname == hostname:
            continue
        _require_hostname_free(session, hostname)
        domain.hostname = hostname
        session.add(domain)
        _flush_or_conflict(session, hostname)


async def delete_domains_for_service(
    session: Session, *, service_id: uuid.UUID, deployment_ids: list[uuid.UUID]
) -> None:
    """Remove every Domain that points at a service or one of its deployments.

    Both directions matter: a system domain targets the service, while a
    pinned Phase 5 preview URL targets one of its deployments. Leaving either
    behind would orphan a row whose CHECK constraint says it must have a
    target.
    """
    for domain in session.exec(select(Domain).where(Domain.service_id == service_id)).all():
        session.delete(domain)
    if deployment_ids:
        rows = session.exec(
            select(Domain).where(Domain.deployment_id.in_(deployment_ids))  # type: ignore[attr-defined]
        ).all()
        for domain in rows:
            session.delete(domain)


async def delete_domains_for_environment(session: Session, *, environment_id: uuid.UUID) -> None:
    """Sweep any Domain still attached to an environment being torn down."""
    rows = session.exec(select(Domain).where(Domain.environment_id == environment_id)).all()
    for domain in rows:
        session.delete(domain)


# --------------------------------------------------------------------------
# Public CRUD.
# --------------------------------------------------------------------------


async def list_domains(session: Session, environment_id: uuid.UUID) -> list[Domain]:
    environment = _require_environment(session, environment_id)
    rows = session.exec(
        select(Domain).where(Domain.environment_id == environment.id).order_by(Domain.hostname)
    ).all()
    return list(rows)


async def list_domains_for_service(session: Session, service_id: uuid.UUID) -> list[Domain]:
    """Every hostname that resolves to a service, system domain included.

    This is what the canvas shows on a service node.
    """
    service = session.get(Service, service_id)
    if service is None:
        raise NotFoundError(
            f"service {service_id} does not exist",
            details={"service_id": str(service_id)},
        )
    rows = session.exec(
        select(Domain).where(Domain.service_id == service.id).order_by(Domain.hostname)
    ).all()
    return list(rows)


async def get_domain(session: Session, domain_id: uuid.UUID) -> Domain:
    return _require_domain(session, domain_id)


async def create_domain(
    session: Session, environment_id: uuid.UUID, payload: DomainCreate
) -> Domain:
    environment = _require_environment(session, environment_id)
    _validate_target(
        session,
        environment=environment,
        target_type=payload.target_type,
        service_id=payload.service_id,
        deployment_id=payload.deployment_id,
    )
    _require_hostname_free(session, payload.hostname)

    domain = Domain(
        hostname=payload.hostname,
        environment_id=environment.id,
        target_type=payload.target_type,
        service_id=payload.service_id,
        deployment_id=payload.deployment_id,
        # Not client-settable. A system domain is an artefact of a service.
        is_system=False,
        tls_enabled=resolve_tls_enabled(payload.tls_enabled),
    )
    session.add(domain)
    _flush_or_conflict(session, payload.hostname)
    session.commit()
    session.refresh(domain)
    return domain


async def update_domain(
    session: Session, domain_id: uuid.UUID, payload: DomainUpdate
) -> Domain:
    domain = _require_domain(session, domain_id)
    _reject_system_domain(domain, verb="updated")

    data = payload.model_dump(exclude_unset=True)
    target_type = data.get("target_type", domain.target_type)
    service_id = data.get("service_id", domain.service_id)
    deployment_id = data.get("deployment_id", domain.deployment_id)
    hostname = data.get("hostname", domain.hostname)

    return await _apply_domain_write(
        session,
        domain=domain,
        hostname=hostname,
        target_type=target_type,
        service_id=service_id,
        deployment_id=deployment_id,
        tls_enabled=data.get("tls_enabled", domain.tls_enabled),
    )


async def replace_domain(
    session: Session, domain_id: uuid.UUID, payload: DomainReplace
) -> Domain:
    domain = _require_domain(session, domain_id)
    _reject_system_domain(domain, verb="replaced")
    return await _apply_domain_write(
        session,
        domain=domain,
        hostname=payload.hostname,
        target_type=payload.target_type,
        service_id=payload.service_id,
        deployment_id=payload.deployment_id,
        tls_enabled=resolve_tls_enabled(payload.tls_enabled),
    )


async def delete_domain(session: Session, domain_id: uuid.UUID) -> None:
    domain = _require_domain(session, domain_id)
    _reject_system_domain(domain, verb="deleted")
    session.delete(domain)
    session.commit()


# --------------------------------------------------------------------------
# Internals.
# --------------------------------------------------------------------------


async def _apply_domain_write(
    session: Session,
    *,
    domain: Domain,
    hostname: str,
    target_type: DomainTargetType,
    service_id: uuid.UUID | None,
    deployment_id: uuid.UUID | None,
    tls_enabled: bool,
) -> Domain:
    environment = _require_environment(session, domain.environment_id)
    _validate_target(
        session,
        environment=environment,
        target_type=target_type,
        service_id=service_id,
        deployment_id=deployment_id,
    )
    if hostname != domain.hostname:
        _require_hostname_free(session, hostname)

    domain.hostname = hostname
    domain.target_type = target_type
    domain.service_id = service_id
    domain.deployment_id = deployment_id
    domain.tls_enabled = tls_enabled

    session.add(domain)
    _flush_or_conflict(session, hostname)
    session.commit()
    session.refresh(domain)
    return domain


def _reject_system_domain(domain: Domain, *, verb: str) -> None:
    if domain.is_system:
        raise ForbiddenError(
            f"system domain {domain.hostname} cannot be {verb} directly; "
            "it follows its service",
            code=SYSTEM_DOMAIN_IMMUTABLE,
            details={"domain_id": str(domain.id), "hostname": domain.hostname},
        )


def _validate_target(
    session: Session,
    *,
    environment: Environment,
    target_type: DomainTargetType,
    service_id: uuid.UUID | None,
    deployment_id: uuid.UUID | None,
) -> None:
    """Enforce the Domain CHECK constraint before the database has to.

    The constraint is real and stays real — this is here so the client gets a
    422 with a readable message instead of a leaked IntegrityError.
    """
    if service_id is not None and deployment_id is not None:
        raise InvalidRequestError(
            "set exactly one of service_id / deployment_id, not both",
            details={"service_id": str(service_id), "deployment_id": str(deployment_id)},
        )
    if service_id is None and deployment_id is None:
        raise InvalidRequestError(
            "set exactly one of service_id / deployment_id, neither was given",
            details={"target_type": target_type.value},
        )
    if target_type is DomainTargetType.SERVICE and service_id is None:
        raise InvalidRequestError("target_type=service requires service_id")
    if target_type is DomainTargetType.DEPLOYMENT and deployment_id is None:
        raise InvalidRequestError("target_type=deployment requires deployment_id")

    if service_id is not None:
        service = session.get(Service, service_id)
        if service is None:
            raise NotFoundError(
                f"service {service_id} does not exist",
                details={"service_id": str(service_id)},
            )
        _require_same_environment(service, environment)

    if deployment_id is not None:
        deployment = session.get(Deployment, deployment_id)
        if deployment is None:
            raise NotFoundError(
                f"deployment {deployment_id} does not exist",
                details={"deployment_id": str(deployment_id)},
            )
        service = session.get(Service, deployment.service_id)
        if service is None:
            raise NotFoundError(
                f"deployment {deployment_id} has no service",
                details={"deployment_id": str(deployment_id)},
            )
        _require_same_environment(service, environment)


def _require_same_environment(service: Service, environment: Environment) -> None:
    if service.environment_id != environment.id:
        raise InvalidRequestError(
            "a domain can only target something inside its own environment",
            details={
                "environment_id": str(environment.id),
                "service_environment_id": str(service.environment_id),
            },
        )


def _require_hostname_free(session: Session, hostname: str) -> None:
    existing = session.exec(select(Domain).where(Domain.hostname == hostname)).first()
    if existing is None:
        return
    raise ConflictError(
        f"hostname {hostname} is already in use",
        code=HOSTNAME_TAKEN,
        details={
            "hostname": hostname,
            "domain_id": str(existing.id),
            "is_system": existing.is_system,
        },
    )


def _flush_or_conflict(session: Session, hostname: str) -> None:
    """Turn the unique-hostname IntegrityError into a clean 409.

    The pre-check above catches the ordinary case with a better message; this
    catches the race between two concurrent creates of the same hostname.
    """
    try:
        session.flush()
    except IntegrityError as err:
        session.rollback()
        raise ConflictError(
            f"hostname {hostname} is already in use",
            code=HOSTNAME_TAKEN,
            details={"hostname": hostname},
        ) from err


def _system_domains_for_service(session: Session, service_id: uuid.UUID) -> list[Domain]:
    rows = session.exec(
        select(Domain).where(
            Domain.service_id == service_id,
            Domain.is_system.is_(True),  # type: ignore[attr-defined]
        )
    ).all()
    return list(rows)


def _require_environment(session: Session, environment_id: uuid.UUID) -> Environment:
    environment = session.get(Environment, environment_id)
    if environment is None:
        raise NotFoundError(
            f"environment {environment_id} does not exist",
            details={"environment_id": str(environment_id)},
        )
    return environment


def _require_domain(session: Session, domain_id: uuid.UUID) -> Domain:
    domain = session.get(Domain, domain_id)
    if domain is None:
        raise NotFoundError(
            f"domain {domain_id} does not exist",
            details={"domain_id": str(domain_id)},
        )
    return domain
