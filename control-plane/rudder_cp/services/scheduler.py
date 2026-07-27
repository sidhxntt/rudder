from sqlmodel import Session, select

from rudder_cp.models import Node, NodeStatus, Service


def select_node_for_service(db: Session, service: Service) -> Node:
    """
    Selects the best node for a service based on available resources.

    1. Filters nodes to find healthy ones with sufficient free CPU and memory.
    2. Excludes nodes that do not have required volumes (placeholder).
    3. Selects the node with the lowest `memory_allocated_mb` / `memory_total_mb` ratio.
    4. Applies a `SELECT ... FOR UPDATE` row lock on the chosen `Node`.
    """
    # TODO: Phase 5 - volume placement
    # required_volumes = db.exec(sa.select(Volume).where(Volume.service_id == service.id)).all()

    # Lock the healthy candidates before evaluating capacity. Locking only the
    # final choice lets two schedulers both read stale allocations and overbook
    # a node before either transaction reserves its resources.
    healthy_nodes = db.exec(
        select(Node)
        .where(Node.status == NodeStatus.HEALTHY)
        .with_for_update()
    ).all()
    candidates = [
        node
        for node in healthy_nodes
        if node.cpu_total >= node.cpu_allocated + service.cpu_limit
        and node.memory_total_mb >= node.memory_allocated_mb + service.memory_limit_mb
    ]

    if not candidates:
        raise ValueError("No nodes with sufficient capacity available.")

    # Select the node with the lowest memory utilization ratio
    best_node = min(
        candidates,
        key=lambda n: (
            n.memory_allocated_mb / n.memory_total_mb
            if n.memory_total_mb > 0
            else float("inf")
        ),
    )

    return best_node
