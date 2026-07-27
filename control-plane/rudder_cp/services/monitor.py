"""Instance state reconciliation.

The control plane owns desired state; the node owns actual state. Without
something closing the gap, a container that dies leaves the database claiming
`healthy` forever and Traefik routing to a corpse — which is exactly what
happens if you `docker kill` a container.

This is deliberately NOT the Phase 2 reconciler. It does not reschedule, it does
not make placement decisions, and it never starts anything. It observes and
records, and re-renders routing when what it observed changed.

Two rules from the PRD's "where you are likely to be wrong":

  idempotent  — running it twice in a row changes nothing the second time
  no thrash   — it writes only on an actual status change, and re-renders
                routing only when a write happened
"""

import logging

from sqlmodel import Session, select

from rudder_cp.config import Settings
from rudder_cp.models import (
    Deployment,
    DeploymentStatus,
    GitHubImport,
    Instance,
    InstanceStatus,
    Node,
)
from rudder_cp.services import traefik
from rudder_cp.services.agent_client import AgentClient, AgentError

log = logging.getLogger("rudder_cp.monitor")

# Instances the deploy path is actively working on are off limits — it owns
# their lifecycle until the deployment reaches a terminal status. Touching a
# `starting` instance mid-deploy would race the health poll.
_OBSERVED_STATUSES = (InstanceStatus.HEALTHY, InstanceStatus.UNHEALTHY)

_AGENT_TO_INSTANCE = {
    "healthy": InstanceStatus.HEALTHY,
    "starting": InstanceStatus.HEALTHY,
    "unhealthy": InstanceStatus.UNHEALTHY,
    "draining": InstanceStatus.DRAINING,
    "stopped": InstanceStatus.STOPPED,
}


async def reconcile_instances(
    session: Session,
    agent: AgentClient,
    settings: Settings,
) -> int:
    """Compare recorded instance state against the node. Returns changes made."""
    instances = _live_instances(session, settings)
    changed = 0

    for instance in instances:
        if instance.container_id is None:
            continue
        node = session.get(Node, instance.node_id)
        if node is None:
            log.warning(
                "could not inspect %s: owning node %s is missing",
                instance.id,
                instance.node_id,
            )
            continue
        observed = await _observe(agent.for_node(node.ip_address), instance.container_id)
        if observed is None or observed is instance.status:
            continue
        log.info(
            "instance %s: %s -> %s (observed on node)",
            instance.id,
            instance.status.value,
            observed.value,
        )
        instance.status = observed
        session.add(instance)
        changed += 1

    if changed:
        session.commit()
        # Routing is derived from healthy instances, so a status change that is
        # not followed by a re-render leaves Traefik pointing at the old set.
        await traefik.render_all(session, settings)
    return changed


def _live_instances(session: Session, settings: Settings) -> list[Instance]:
    """Return Docker-owned instances that are safe to inspect through an agent.

    A Phase 3 imported release stores Kubernetes pod IDs in ``Instance`` so
    the existing deployment and history projections stay useful.  They are
    not Docker container IDs, though.  Asking a node agent to inspect one
    returns ``container_not_found`` and used to turn a ready Kubernetes
    release into a false failed state two seconds after promotion.
    """
    statement = (
        select(Instance)
        .join(Deployment, Deployment.id == Instance.deployment_id)  # type: ignore[arg-type]
        .where(
            Deployment.status == DeploymentStatus.LIVE,
            Instance.status.in_(_OBSERVED_STATUSES),  # type: ignore[attr-defined]
        )
    )
    if settings.runtime == "kubernetes":
        kubernetes_release_owners = select(GitHubImport.app_service_id)
        statement = statement.where(Deployment.service_id.not_in(kubernetes_release_owners))
    return list(session.exec(statement).all())


async def _observe(agent: AgentClient, container_id: str) -> InstanceStatus | None:
    """Ask the node what it sees. Returns None when the answer is unusable.

    An unreachable agent is not evidence that a container died. Recording
    `stopped` because the network hiccuped would take a healthy service out of
    rotation, so uncertainty means "leave it alone".
    """
    try:
        state = await agent.inspect(container_id)
    except AgentError as exc:
        message = str(exc)
        if "container_not_found" in message or "404" in message:
            # The container is genuinely gone. That is an observation, not a
            # transport failure.
            return InstanceStatus.STOPPED
        log.warning("could not inspect %s: %s", container_id, exc)
        return None
    return _AGENT_TO_INSTANCE.get(state.status)
