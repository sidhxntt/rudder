import asyncio
import logging
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Engine
from sqlmodel import Session, select

from rudder_cp.config import Settings
from rudder_cp.models import Deployment, Instance, Node, Volume
from rudder_cp.models.base import DeploymentStatus, NodeStatus
from rudder_cp.models.base import InstanceStatus as ModelInstanceStatus
from rudder_cp.models.github_import import GitHubImport
from rudder_cp.services.agent_client import AgentClient, AgentError

log = logging.getLogger(__name__)


async def run_reconciler(
    engine: Engine, stop_event: asyncio.Event, agent_client: AgentClient, settings: Settings
) -> None:
    """Runs the reconciler loop until the stop event is set."""
    log.info("reconciler started")
    while not stop_event.is_set():
        try:
            with Session(engine) as session:
                await reconcile_state(session, agent_client, settings=settings)
        except Exception as e:
            log.error(f"Error in reconciler loop: {e}", exc_info=True)

        try:
            # Wait for 15 seconds or until stop event is set
            await asyncio.wait_for(stop_event.wait(), timeout=15)
        except TimeoutError:
            pass
    log.info("reconciler stopped")


async def reconcile_state(
    db: Session, agent_client: AgentClient, *, settings: Settings | None = None
) -> None:
    """Periodically checks that the state of running containers on each node
    matches the state of Instance rows in the database.

    - Marks nodes as UNREACHABLE if they have not sent a heartbeat recently.
    - Marks Instances as UNREACHABLE if their node is unhealthy.
    - Marks Instances as UNREACHABLE if they are not in the node's last report.
    - Deletes containers that are on a node but not in the database.
    """
    kubernetes_release_owners = _kubernetes_release_owners(db, settings)
    await _reconcile_unresponsive_nodes(db, kubernetes_release_owners)
    await _reconcile_running_instances(db, agent_client, kubernetes_release_owners)
    _queue_replacements_for_lost_instances(db, kubernetes_release_owners)

    db.commit()


async def _reconcile_unresponsive_nodes(
    db: Session, kubernetes_release_owners: set[UUID]
) -> None:
    """Finds nodes that have missed their heartbeat and marks them UNREACHABLE."""
    # TODO: Make threshold configurable
    unresponsive_threshold = datetime.now(UTC) - timedelta(seconds=30)
    unresponsive_nodes_stmt = select(Node).where(
        Node.status == NodeStatus.HEALTHY,
        Node.last_heartbeat_at < unresponsive_threshold,
    )
    unresponsive_nodes = db.exec(unresponsive_nodes_stmt).all()

    for node in unresponsive_nodes:
        if _is_kubernetes_accounting_node(node):
            # GKE owns Pod liveness. This row exists only while Instance.node_id
            # is required for the legacy Docker-runtime schema.
            continue
        node.status = NodeStatus.UNREACHABLE
        db.add(node)

        instances_on_node_stmt = select(Instance).where(Instance.node_id == node.id)
        for instance in db.exec(instances_on_node_stmt):
            deployment = db.get(Deployment, instance.deployment_id)
            if deployment is not None and deployment.service_id in kubernetes_release_owners:
                # The Kind/Kubernetes control plane, not the Docker node
                # heartbeat, owns pod liveness.
                continue
            instance.status = ModelInstanceStatus.UNREACHABLE
            db.add(instance)


def _is_kubernetes_accounting_node(node: Node) -> bool:
    return bool(
        isinstance(node.reported_state, dict)
        and node.reported_state.get("runtime") == "kubernetes"
        and node.reported_state.get("accounting_only") is True
    )


def _queue_replacements_for_lost_instances(
    db: Session, kubernetes_release_owners: set[UUID]
) -> None:
    """Recreate a release when its last healthy instance was lost with a node.

    A replacement is a normal queued deployment, so it follows the existing
    build, placement, health-check, and atomic traffic-shift path. The guard
    against existing in-flight deployments keeps a continuously unreachable
    node from creating one release per reconciliation tick.
    """
    statement = (
        select(Instance)
        .join(Deployment, Deployment.id == Instance.deployment_id)  # type: ignore[arg-type]
        .where(
            Instance.status == ModelInstanceStatus.UNREACHABLE,
            Deployment.status == DeploymentStatus.LIVE,
        )
    )
    if kubernetes_release_owners:
        statement = statement.where(Deployment.service_id.not_in(kubernetes_release_owners))
    lost = db.exec(statement).all()
    for instance in lost:
        deployment = db.get(Deployment, instance.deployment_id)
        if deployment is None:
            continue
        service_id = deployment.service_id
        # A host-local persistent volume cannot be safely mounted on a second
        # node while the first node is merely unreachable.  Automatic recovery
        # is therefore deliberately stateless-only; an operator must recover
        # stateful workloads after fencing or restoring the original node.
        if db.exec(select(Volume).where(Volume.service_id == service_id)).first() is not None:
            log.warning(
                "not auto-rescheduling stateful service %s after node loss",
                service_id,
            )
            continue
        healthy_exists = db.exec(
            select(Instance)
            .join(Deployment, Deployment.id == Instance.deployment_id)  # type: ignore[arg-type]
            .where(
                Deployment.service_id == service_id,
                Instance.status == ModelInstanceStatus.HEALTHY,
            )
        ).first()
        if healthy_exists is not None:
            continue
        in_flight = db.exec(
            select(Deployment).where(
                Deployment.service_id == service_id,
                Deployment.status.in_(  # type: ignore[attr-defined]
                    [
                        DeploymentStatus.QUEUED,
                        DeploymentStatus.BUILDING,
                        DeploymentStatus.DEPLOYING,
                    ]
                ),
            )
        ).first()
        if in_flight is None:
            db.add(
                Deployment(
                    service_id=service_id,
                    commit_sha=deployment.commit_sha,
                    status=DeploymentStatus.QUEUED,
                )
            )


async def _reconcile_running_instances(
    db: Session,
    agent_client: AgentClient,
    kubernetes_release_owners: set[UUID],
) -> None:
    """Compares the Instances that should be running on each node with the set
    of containers reported by that node's agent.
    """
    healthy_nodes = db.exec(select(Node).where(Node.status == NodeStatus.HEALTHY)).all()

    for node in healthy_nodes:
        if not node.reported_state or not node.ip_address:
            continue

        reported_containers = node.reported_state.get("containers", [])
        if not isinstance(reported_containers, list):
            # The agent reported a malformed state
            continue

        # Docker IDs are the stable values persisted in Instance.container_id;
        # names are display-only and vary across Compose releases.
        reported_ids = {
            container["id"]
            for container in reported_containers
            if isinstance(container, dict) and "id" in container
        }

        desired_instances_stmt = select(Instance).where(
            Instance.node_id == node.id,
            Instance.status != ModelInstanceStatus.STOPPED,
        )
        if kubernetes_release_owners:
            desired_instances_stmt = (
                desired_instances_stmt.join(
                    Deployment, Deployment.id == Instance.deployment_id  # type: ignore[arg-type]
                ).where(
                    Deployment.service_id.not_in(kubernetes_release_owners)
                )
            )
        desired_by_container_id = {
            instance.container_id: instance
            for instance in db.exec(desired_instances_stmt)
            if instance.container_id
        }

        # docker compose ps emits shortened container IDs while Docker's API
        # (and therefore heartbeats) uses full IDs. Treat either form as the
        # same container so a healthy Compose release is not mistaken for a
        # lost instance and re-scheduled on every reconciliation interval.
        matching_reported_ids = {
            reported_id
            for reported_id in reported_ids
            if any(
                _same_container_id(reported_id, desired_id)
                for desired_id in desired_by_container_id
            )
        }

        # An instance is in the DB but was not in the agent's last report
        for container_id, instance in desired_by_container_id.items():
            if any(_same_container_id(container_id, reported_id) for reported_id in reported_ids):
                continue
            instance.status = ModelInstanceStatus.UNREACHABLE
            db.add(instance)

        # A container was reported by the agent but is not in the DB
        # Never touch arbitrary user/system containers. Only a container the
        # agent reports as Rudder-owned can be garbage-collected.
        extra_ids = reported_ids - matching_reported_ids
        node_agent = agent_client.for_node(node.ip_address)
        for container in reported_containers:
            if not isinstance(container, dict):
                continue
            container_id = container.get("id")
            labels = container.get("labels")
            if (
                not isinstance(container_id, str)
                or container_id not in extra_ids
                or not isinstance(labels, dict)
                or "rudder.deployment" not in labels
            ):
                continue
            try:
                await node_agent.remove(container_id, drain_seconds=0)
            except AgentError as exc:
                log.warning(
                    "failed to remove orphan %s on %s: %s",
                    container_id,
                    node.hostname,
                    exc,
                )


def _same_container_id(left: str, right: str) -> bool:
    """Match full Docker IDs with Compose's unambiguous 12-character form."""
    return left == right or (
        len(left) >= 12
        and len(right) >= 12
        and (left.startswith(right) or right.startswith(left))
    )


def _kubernetes_release_owners(db: Session, settings: Settings | None) -> set[UUID]:
    """Return imported release owner services that Kubernetes, not agents, owns."""
    if settings is None or settings.runtime != "kubernetes":
        return set()
    return set(db.exec(select(GitHubImport.app_service_id)).all())
