"""Collect bounded Docker runtime-log snapshots onto control-plane disk."""

from __future__ import annotations

import logging

from kubernetes_asyncio.client import ApiException
from sqlmodel import Session, select

from rudder_cp.config import Settings
from rudder_cp.logs.runtime import RuntimeLogStore
from rudder_cp.models import (
    Deployment,
    GitHubImport,
    GitHubImportService,
    Instance,
    InstanceStatus,
    Node,
    Service,
)
from rudder_cp.runtime.targets import load_kubernetes_client
from rudder_cp.services.agent_client import AgentClient, AgentError
from rudder_cp.services.kubernetes_namespace import environment_namespace

log = logging.getLogger(__name__)

_ACTIVE = (InstanceStatus.HEALTHY, InstanceStatus.UNHEALTHY, InstanceStatus.DRAINING)


async def collect_runtime_logs(
    session: Session, agent: AgentClient, settings: Settings, store: RuntimeLogStore
) -> int:
    """Pull bounded runtime-log tails; never let one workload abort a tick."""
    if settings.runtime == "kubernetes":
        return await _collect_kubernetes_runtime_logs(session, settings, store)
    if settings.runtime != "docker":
        return 0
    rows = session.exec(
        select(Instance, Deployment, Node)
        .join(Deployment, Deployment.id == Instance.deployment_id)  # type: ignore[arg-type]
        .join(Node, Node.id == Instance.node_id)  # type: ignore[arg-type]
        .where(Instance.status.in_(_ACTIVE))  # type: ignore[attr-defined]
    ).all()
    written = 0
    for instance, deployment, node in rows:
        if not instance.container_id or not node.ip_address:
            continue
        try:
            snapshot = await agent.for_node(node.ip_address).runtime_logs(instance.container_id)
            written += await store.append_snapshot(
                _service_for_instance(session, deployment, instance),
                snapshot.text,
                dropped_bytes=snapshot.dropped_bytes,
            )
        except AgentError as exc:
            log.warning("could not collect logs for instance %s: %s", instance.id, exc)
    return written


async def _collect_kubernetes_runtime_logs(
    session: Session, settings: Settings, store: RuntimeLogStore
) -> int:
    """Collect Pod tails through the cluster API, never through a node agent."""
    rows = session.exec(
        select(Instance, Deployment, Service)
        .join(Deployment, Deployment.id == Instance.deployment_id)  # type: ignore[arg-type]
        .join(Service, Service.id == Deployment.service_id)  # type: ignore[arg-type]
        .where(Instance.status.in_(_ACTIVE))  # type: ignore[attr-defined]
    ).all()
    api = None
    written = 0
    try:
        api = await load_kubernetes_client(settings)
        for instance, deployment, service in rows:
            if not instance.container_id:
                continue
            namespace = environment_namespace(settings, service.environment_id)
            try:
                snapshot = await api.runtime_logs(namespace, instance.container_id)
                written += await store.append_snapshot(
                    _service_for_instance(session, deployment, instance),
                    snapshot.text,
                    dropped_bytes=snapshot.dropped_bytes,
                )
            except (ApiException, OSError, RuntimeError) as exc:
                log.warning(
                    "could not collect Kubernetes logs for instance %s: %s", instance.id, exc
                )
    except (ApiException, OSError, RuntimeError) as exc:
        log.warning("could not initialize Kubernetes runtime-log collection: %s", exc)
    finally:
        if api is not None:
            try:
                await api.close()
            except (ApiException, OSError, RuntimeError) as exc:
                log.warning("could not close Kubernetes runtime-log client: %s", exc)
    return written


def _service_for_instance(session: Session, deployment: Deployment, instance: Instance):
    """Route Compose-member telemetry to its actual service when known."""
    service_id = deployment.service_id
    if instance.compose_service:
        member = session.exec(
            select(GitHubImportService.service_id)
            .join(
                GitHubImport,
                GitHubImport.id == GitHubImportService.github_import_id,
            )
            .where(
                GitHubImport.app_service_id == deployment.service_id,
                GitHubImportService.compose_service == instance.compose_service,
            )
        ).first()
        if member is not None:
            service_id = member
    return service_id
