
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from rudder_cp.models import Deployment, Instance, Node, Volume
from rudder_cp.models.base import DeploymentStatus, InstanceStatus, NodeStatus
from rudder_cp.services.reconciler import AgentClient, reconcile_state

# In-memory SQLite database for testing
sqlite_file_name = "test.db"
sqlite_url = f"sqlite:///{sqlite_file_name}"
engine = create_engine(sqlite_url, echo=True)


def create_db_and_tables():
    SQLModel.metadata.create_all(engine)


@pytest.fixture(name="session")
def session_fixture():
    create_db_and_tables()
    with Session(engine) as session:
        yield session
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="mock_agent_client")
def mock_agent_client_fixture():
    client = AsyncMock(spec=AgentClient)
    client.for_node.return_value = client
    return client


@pytest.mark.asyncio
async def test_reconcile_marks_unresponsive_node_as_unreachable(
    session: Session, mock_agent_client: MagicMock
):
    # Arrange
    now = datetime.now(UTC)
    responsive_node = Node(hostname="healthy-node", ip_address="1.1.1.1", last_heartbeat_at=now)
    unresponsive_node = Node(
        hostname="unhealthy-node",
        ip_address="2.2.2.2",
        last_heartbeat_at=now - timedelta(seconds=60),
    )
    session.add_all([responsive_node, unresponsive_node])
    session.commit()

    instance_on_unresponsive_node = Instance(
        deployment_id=uuid.uuid4(), node_id=unresponsive_node.id, status=InstanceStatus.HEALTHY
    )
    session.add(instance_on_unresponsive_node)
    session.commit()

    # Act
    await reconcile_state(session, mock_agent_client)

    # Assert
    session.refresh(responsive_node)
    session.refresh(unresponsive_node)
    session.refresh(instance_on_unresponsive_node)

    assert responsive_node.status == NodeStatus.HEALTHY
    assert unresponsive_node.status == NodeStatus.UNREACHABLE
    assert instance_on_unresponsive_node.status == InstanceStatus.UNREACHABLE


@pytest.mark.asyncio
async def test_reconcile_keeps_gke_accounting_projection_healthy(
    session: Session, mock_agent_client: MagicMock
):
    """A GKE projection has no agent heartbeat; Kubernetes owns its health."""
    node = Node(
        hostname="gke-runtime",
        ip_address="0.0.0.0",
        last_heartbeat_at=datetime.now(UTC) - timedelta(seconds=60),
        reported_state={"runtime": "kubernetes", "accounting_only": True},
    )
    session.add(node)
    session.commit()

    await reconcile_state(session, mock_agent_client)

    session.refresh(node)
    assert node.status == NodeStatus.HEALTHY


@pytest.mark.asyncio
async def test_reconcile_marks_missing_instance_as_unreachable(
    session: Session, mock_agent_client: MagicMock
):
    # Arrange
    node = Node(hostname="test-node", ip_address="1.1.1.1", last_heartbeat_at=datetime.now(UTC))
    session.add(node)
    session.commit()

    instance = Instance(
        deployment_id=uuid.uuid4(),
        node_id=node.id,
        container_id="missing-container-id",
        status=InstanceStatus.HEALTHY,
    )
    session.add(instance)

    # The agent reports no containers
    node.reported_state = {"containers": []}
    session.commit()

    # Act
    await reconcile_state(session, mock_agent_client)

    # Assert
    session.refresh(instance)
    assert instance.status == InstanceStatus.UNREACHABLE


@pytest.mark.asyncio
async def test_reconcile_keeps_compose_instance_healthy_when_heartbeat_has_full_id(
    session: Session, mock_agent_client: MagicMock
):
    """Compose reports shortened IDs, but Docker heartbeats use full IDs."""
    node = Node(hostname="test-node", ip_address="1.1.1.1", last_heartbeat_at=datetime.now(UTC))
    session.add(node)
    session.commit()

    short_id = "0123456789ab"
    full_id = short_id + "c" * 52
    deployment = Deployment(service_id=uuid.uuid4(), status=DeploymentStatus.LIVE)
    session.add(deployment)
    session.commit()
    instance = Instance(
        deployment_id=deployment.id,
        node_id=node.id,
        container_id=short_id,
        status=InstanceStatus.HEALTHY,
    )
    session.add(instance)
    node.reported_state = {"containers": [{"id": full_id, "labels": {}}]}
    session.add(node)
    session.commit()

    await reconcile_state(session, mock_agent_client)

    session.refresh(instance)
    assert instance.status == InstanceStatus.HEALTHY


@pytest.mark.asyncio
async def test_reconcile_terminates_extra_container(session: Session, mock_agent_client: MagicMock):
    # Arrange
    node = Node(
        hostname="test-node",
        ip_address="1.1.1.1",
        last_heartbeat_at=datetime.now(UTC),
        reported_state={
            "containers": [
                {
                    "id": "extra-container-id",
                    "labels": {"rudder.deployment": "deployment-id"},
                }
            ]
        },
    )
    session.add(node)
    session.commit()

    # Act
    await reconcile_state(session, mock_agent_client)

    # Assert
    mock_agent_client.remove.assert_awaited_once_with("extra-container-id", drain_seconds=0)


@pytest.mark.asyncio
async def test_reconcile_terminates_container_for_stopped_instance(
    session: Session, mock_agent_client: MagicMock
):
    # Arrange
    node = Node(hostname="test-node", ip_address="1.1.1.1", last_heartbeat_at=datetime.now(UTC))
    session.add(node)
    session.commit()

    stopped_instance = Instance(
        deployment_id=uuid.uuid4(),
        node_id=node.id,
        status=InstanceStatus.STOPPED,
        container_id="stopped-container-id",
    )
    session.add(stopped_instance)

    # Agent reports a container for the stopped instance
    node.reported_state = {
        "containers": [
            {
                "id": "stopped-container-id",
                "labels": {"rudder.deployment": "deployment-id"},
            }
        ]
    }
    session.commit()

    # Act
    await reconcile_state(session, mock_agent_client)

    # Assert
    mock_agent_client.remove.assert_awaited_once_with("stopped-container-id", drain_seconds=0)


@pytest.mark.asyncio
async def test_reconcile_queues_one_replacement_when_a_live_service_loses_its_node(
    session: Session, mock_agent_client: MagicMock
):
    node = Node(
        hostname="lost-node",
        ip_address="1.1.1.1",
        last_heartbeat_at=datetime.now(UTC) - timedelta(seconds=60),
    )
    session.add(node)
    session.commit()
    deployment = Deployment(
        service_id=uuid.uuid4(),
        status=DeploymentStatus.LIVE,
        commit_sha="abc123",
    )
    session.add(deployment)
    session.commit()
    session.add(
        Instance(
            deployment_id=deployment.id,
            node_id=node.id,
            container_id="lost-container",
            status=InstanceStatus.HEALTHY,
        )
    )
    session.commit()

    await reconcile_state(session, mock_agent_client)
    await reconcile_state(session, mock_agent_client)

    queued = session.exec(
        select(Deployment).where(
            Deployment.service_id == deployment.service_id,
            Deployment.status == DeploymentStatus.QUEUED,
        )
    ).all()
    assert len(queued) == 1
    assert queued[0].commit_sha == "abc123"


@pytest.mark.asyncio
async def test_reconcile_does_not_auto_reschedule_a_stateful_service(
    session: Session, mock_agent_client: MagicMock
):
    node = Node(
        hostname="lost-node",
        ip_address="1.1.1.1",
        last_heartbeat_at=datetime.now(UTC) - timedelta(seconds=60),
    )
    session.add(node)
    session.commit()
    service_id = uuid.uuid4()
    deployment = Deployment(
        service_id=service_id,
        status=DeploymentStatus.LIVE,
        commit_sha="abc123",
    )
    session.add_all(
        [
            deployment,
            Volume(service_id=service_id, mount_path="/var/lib/data"),
        ]
    )
    session.commit()
    session.add(
        Instance(
            deployment_id=deployment.id,
            node_id=node.id,
            container_id="lost-container",
            status=InstanceStatus.HEALTHY,
        )
    )
    session.commit()

    await reconcile_state(session, mock_agent_client)

    queued = session.exec(
        select(Deployment).where(
            Deployment.service_id == service_id,
            Deployment.status == DeploymentStatus.QUEUED,
        )
    ).all()
    assert queued == []
