"""Shared immutable deployment restore primitive.

Both the dashboard deployment endpoint and the operations worker use this
function.  Keeping it here prevents the two paths from drifting into one path
that rebuilds source and another that changes traffic safely.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlmodel import Session, select

from rudder_cp.config import Settings
from rudder_cp.models import (
    Deployment,
    DeploymentStatus,
    Domain,
    Environment,
    GitHubImportService,
    Instance,
    InstanceStatus,
    Service,
)
from rudder_cp.runtime.kubernetes import PublicRouteSpec
from rudder_cp.runtime.models import dns_label
from rudder_cp.runtime.targets import load_kubernetes_client
from rudder_cp.services import traefik
from rudder_cp.services.builder import validate_gke_image
from rudder_cp.services.kubernetes_namespace import environment_namespace


async def restore_immutable_deployment(
    session: Session, *, deployment_id: UUID, settings: Settings
) -> Deployment:
    """Promote an existing healthy immutable release; never build or restart it."""
    source = session.get(Deployment, deployment_id)
    if source is None:
        raise HTTPException(status_code=404, detail="No such deployment")
    if source.status not in {DeploymentStatus.LIVE, DeploymentStatus.SUPERSEDED}:
        raise HTTPException(status_code=422, detail="Only successful deployments can be restored")
    healthy_target = session.exec(
        select(Instance).where(
            Instance.deployment_id == source.id,
            Instance.status == InstanceStatus.HEALTHY,
        )
    ).first()
    if healthy_target is None:
        raise HTTPException(status_code=422, detail="Immutable restore target is not healthy")
    current = session.exec(
        select(Deployment).where(
            Deployment.service_id == source.service_id,
            Deployment.status == DeploymentStatus.LIVE,
            Deployment.id != source.id,
        )
    ).all()
    # For Kubernetes, switch the stable Ingress before committing the
    # dashboard's live pointer. If the API call fails, the caller can record a
    # failed rollback operation without a false "live" deployment row.
    if settings.runtime == "kubernetes":
        if settings.kubernetes_target == "gke":
            validate_gke_image(source.image_tag or "")
        await _restore_kubernetes_public_route(session, source=source, settings=settings)
    for deployment in current:
        deployment.status = DeploymentStatus.SUPERSEDED
        session.add(deployment)
    source.status = DeploymentStatus.LIVE
    source.error_message = None
    source.became_live_at = datetime.now(UTC)
    session.add(source)
    session.commit()
    # This is the public-route promotion checkpoint. The target was verified
    # healthy before we moved the live pointer; restoring can neither build
    # source nor recreate a workload. Kubernetes traffic was moved above so
    # its external API failure cannot commit a misleading live pointer.
    if settings.runtime != "kubernetes":
        await traefik.render_all(session, settings)
    session.refresh(source)
    return source


async def _restore_kubernetes_public_route(
    session: Session, *, source: Deployment, settings: Settings
) -> None:
    """Point the stable Ingress back at a healthy immutable Kubernetes release.

    Kubernetes candidates deliberately keep their immutable workloads after a
    later release becomes live.  A rollback therefore replaces only the
    stable, per-service Ingress backend.  It must never invoke the build
    system, create a new Deployment, or restart the restored pods.
    """
    service = session.get(Service, source.service_id)
    if service is None:
        raise HTTPException(status_code=404, detail="Rollback service no longer exists")
    mapping = session.exec(
        select(GitHubImportService).where(GitHubImportService.service_id == service.id)
    ).first()
    if mapping is None or not mapping.is_public:
        # Private workers and data services have no public traffic pointer to
        # move. Their immutable release metadata is still restored above.
        return
    if service.container_port <= 0:
        raise HTTPException(status_code=422, detail="Public rollback service has no container port")
    domain = session.exec(
        select(Domain)
        .where(Domain.service_id == service.id)
        .order_by(Domain.is_system.desc(), Domain.created_at)
    ).first()
    if domain is None:
        raise HTTPException(status_code=422, detail="Public rollback service has no domain")
    environment = session.get(Environment, service.environment_id)
    if environment is None:
        raise HTTPException(status_code=404, detail="Rollback environment no longer exists")

    namespace = dns_label(environment_namespace(settings, environment.id))
    workload_name = dns_label(f"{mapping.compose_service}-{str(source.id)[:8]}")
    route = PublicRouteSpec(
        name=dns_label(f"route-{mapping.compose_service}"),
        host=domain.hostname,
        backend_service_name=workload_name,
        backend_port=service.container_port,
        labels={
            "rudder.service": dns_label(str(service.id)),
            "rudder.release": dns_label(str(source.id)),
            "rudder.route": dns_label(mapping.compose_service),
        },
    )
    api = await load_kubernetes_client(settings)
    try:
        await api.promote_public_service(namespace, route)
    finally:
        await api.close()
