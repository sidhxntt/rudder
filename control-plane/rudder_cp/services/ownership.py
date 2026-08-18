"""Tenant ownership guards shared by resource routers.

The public API deliberately treats resources owned by somebody else exactly
like absent resources.  That both prevents mutations and avoids leaking the
existence of another tenant's graph.
"""

from __future__ import annotations

from uuid import UUID

from sqlmodel import Session, select

from rudder_cp.models import Domain, Environment, Project, Service
from rudder_cp.schemas.common import NotFoundError


def require_owned_project(session: Session, project_id: UUID, owner_id: UUID) -> Project:
    project = session.get(Project, project_id)
    if project is None or project.owner_id != owner_id:
        raise NotFoundError(f"project {project_id} does not exist")
    return project


def list_owned_projects(session: Session, owner_id: UUID) -> list[Project]:
    return list(
        session.exec(
            select(Project).where(Project.owner_id == owner_id).order_by(Project.created_at)
        ).all()
    )


def require_owned_environment(
    session: Session, environment_id: UUID, owner_id: UUID
) -> Environment:
    environment = session.get(Environment, environment_id)
    if environment is None:
        raise NotFoundError(f"environment {environment_id} does not exist")
    require_owned_project(session, environment.project_id, owner_id)
    return environment


def require_owned_service(session: Session, service_id: UUID, owner_id: UUID) -> Service:
    service = session.get(Service, service_id)
    if service is None:
        raise NotFoundError(f"service {service_id} does not exist")
    require_owned_environment(session, service.environment_id, owner_id)
    return service


def require_owned_domain(session: Session, domain_id: UUID, owner_id: UUID) -> Domain:
    domain = session.get(Domain, domain_id)
    if domain is None:
        raise NotFoundError(f"domain {domain_id} does not exist")
    require_owned_environment(session, domain.environment_id, owner_id)
    return domain
