"""Service layer for node management.
"""

from datetime import UTC, datetime

from sqlmodel import Session, select

from rudder_cp.models import Deployment, Instance, Node, Service
from rudder_cp.models.base import DeploymentStatus, InstanceStatus, NodeStatus
from rudder_cp.schemas.nodes import ContainerState


def register_node(
    db: Session,
    hostname: str,
    *,
    ip_address: str,
    cpu_total: float,
    memory_total_mb: int,
) -> Node:
    """Register a node, creating or updating it as necessary."""
    node = db.exec(select(Node).where(Node.hostname == hostname)).first()
    if not node:
        node = Node(hostname=hostname, ip_address=ip_address)

    # Capacity belongs to the agent, not a local default. Refresh it on every
    # registration so a restarted or resized node can accept placements again.
    node.cpu_total = cpu_total
    node.memory_total_mb = memory_total_mb
    node.ip_address = ip_address
    node.status = NodeStatus.HEALTHY
    db.add(node)
    db.commit()
    db.refresh(node)

    return node


def process_heartbeat(db: Session, hostname: str, container_states: list[ContainerState]) -> None:
    """Process a heartbeat from a node."""
    node = db.exec(select(Node).where(Node.hostname == hostname)).first()
    if not node:
        # Should not happen if the agent registered first, but we can be defensive.
        # A heartbeat without prior registration cannot safely invent capacity.
        return

    node.last_heartbeat_at = datetime.now(UTC)
    node.status = NodeStatus.HEALTHY
    node.heartbeat_generation += 1
    node.reported_state = {
        "containers": [container.model_dump(mode="json") for container in container_states]
    }
    db.add(node)
    db.commit()

    # Reconcile container states. Docker's API sends full 64-character IDs;
    # Compose's `ps` output commonly records 12-character IDs. Match either
    # unambiguous representation so a healthy Compose release does not remain
    # stuck as unreachable after a heartbeat.
    instances = db.exec(select(Instance).where(Instance.node_id == node.id)).all()
    # This is a simplified version. A full reconciler would be more complex.
    for container_state in container_states:
        instance = next(
            (
                candidate
                for candidate in instances
                if candidate.container_id
                and _same_container_id(candidate.container_id, container_state.id)
            ),
            None,
        )
        if instance:
            # Docker has no HEALTHCHECK for many perfectly valid application
            # images.  The deployment path independently promoted this
            # instance after its HTTP/TCP probe succeeded, so a subsequent
            # heartbeat reporting Docker's generic ``starting`` must not
            # regress the user-visible state back from healthy.
            if container_state.status == "starting":
                deployment = db.get(Deployment, instance.deployment_id)
                if deployment is not None and deployment.status is DeploymentStatus.LIVE:
                    instance.status = InstanceStatus.HEALTHY
                elif instance.status is InstanceStatus.HEALTHY:
                    continue
                else:
                    instance.status = container_state.status
            else:
                instance.status = container_state.status
            db.add(instance)

    _recalculate_allocated_capacity(db, node)
    db.commit()


def _same_container_id(left: str, right: str) -> bool:
    """Full Docker IDs and Compose's 12-character IDs identify one container."""
    return left == right or (
        len(left) >= 12
        and len(right) >= 12
        and (left.startswith(right) or right.startswith(left))
    )


def _recalculate_allocated_capacity(db: Session, node: Node) -> None:
    """Make reservations converge to the active release instances on a node.

    Reservations are normally incremented/decremented during deployment and
    drain. A control-plane restart during either step must not leave a node
    permanently full. The next heartbeat repairs that accounting from the
    release instances the node actually reports as active.
    """
    active_instances = db.exec(
        select(Instance)
        .join(Deployment, Deployment.id == Instance.deployment_id)  # type: ignore[arg-type]
        .where(
            Instance.node_id == node.id,
            Instance.status.in_(  # type: ignore[attr-defined]
                [InstanceStatus.HEALTHY, InstanceStatus.STARTING]
            ),
            Deployment.status.in_(  # type: ignore[attr-defined]
                [DeploymentStatus.LIVE, DeploymentStatus.DEPLOYING]
            ),
        )
    ).all()
    active_deployment_ids = {instance.deployment_id for instance in active_instances}
    cpu = 0.0
    memory_mb = 0
    for deployment_id in active_deployment_ids:
        deployment = db.get(Deployment, deployment_id)
        if deployment is None:
            continue
        service = db.get(Service, deployment.service_id)
        if service is None:
            continue
        cpu += service.cpu_limit
        memory_mb += service.memory_limit_mb
    node.cpu_allocated = cpu
    node.memory_allocated_mb = memory_mb
    db.add(node)


def get_all_nodes_with_instances(db: Session) -> list[tuple[Node, list[Instance]]]:
    """Retrieve all nodes with their instances."""
    nodes = db.exec(select(Node).order_by(Node.hostname)).all()
    instances = db.exec(select(Instance)).all()

    # Group instances by node_id
    instances_by_node_id = {}
    for instance in instances:
        instances_by_node_id.setdefault(instance.node_id, []).append(instance)

    return [(node, instances_by_node_id.get(node.id, [])) for node in nodes]
