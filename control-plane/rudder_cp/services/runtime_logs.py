"""Collect bounded Docker runtime-log snapshots onto control-plane disk."""

from __future__ import annotations

import logging

from sqlmodel import Session, select

from rudder_cp.config import Settings
from rudder_cp.logs.runtime import RuntimeLogStore
from rudder_cp.models import Deployment, Instance, InstanceStatus, Node
from rudder_cp.services.agent_client import AgentClient, AgentError

log = logging.getLogger(__name__)

_ACTIVE = (InstanceStatus.HEALTHY, InstanceStatus.UNHEALTHY, InstanceStatus.DRAINING)


async def collect_runtime_logs(
    session: Session, agent: AgentClient, settings: Settings, store: RuntimeLogStore
) -> int:
    """Pull a capped tail from each Docker instance; never let one node abort a tick."""
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
                deployment.service_id, snapshot.text, dropped_bytes=snapshot.dropped_bytes
            )
        except AgentError as exc:
            log.warning("could not collect logs for instance %s: %s", instance.id, exc)
    return written
