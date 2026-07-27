"""Node registration and heartbeat state are the Phase 2 control-plane boundary."""

import uuid

import pytest
from sqlmodel import Session, SQLModel, create_engine

from rudder_cp.models import Deployment, Instance, Node
from rudder_cp.models.base import DeploymentStatus
from rudder_cp.models.base import InstanceStatus as ModelInstanceStatus
from rudder_cp.routers.nodes import list_nodes
from rudder_cp.schemas.nodes import ContainerState, InstanceStatus
from rudder_cp.services.nodes import process_heartbeat, register_node


def test_registration_records_the_reachable_agent_address_and_heartbeat_state() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            node = register_node(
                session,
                "node-a",
                ip_address="10.42.0.4",
                cpu_total=4,
                memory_total_mb=8192,
            )
            assert node.ip_address == "10.42.0.4"

            process_heartbeat(
                session,
                "node-a",
                [
                    ContainerState(
                        id="container-a",
                        name="rudder-app-a",
                        status=InstanceStatus.HEALTHY,
                        docker_status="running",
                        labels={"rudder.deployment": "deployment-a"},
                    )
                ],
            )
            session.refresh(node)
            assert node.last_heartbeat_at is not None
            assert node.reported_state == {
                "containers": [
                    {
                        "id": "container-a",
                        "name": "rudder-app-a",
                        "status": "healthy",
                        "docker_status": "running",
                        "docker_health": None,
                        "exit_code": None,
                        "started_at": None,
                        "ip_address": None,
                        "image": None,
                        "labels": {"rudder.deployment": "deployment-a"},
                    }
                ]
            }
    finally:
        SQLModel.metadata.drop_all(engine)


def test_heartbeat_matches_compose_short_container_ids_and_restores_live_health() -> None:
    """Docker heartbeats use full IDs while Compose persists its 12-char form."""
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            node = register_node(
                session,
                "node-a",
                ip_address="10.42.0.4",
                cpu_total=4,
                memory_total_mb=8192,
            )
            node.cpu_allocated = 4
            node.memory_allocated_mb = 4096
            session.add(node)
            session.commit()
            deployment = Deployment(service_id=uuid.uuid4(), status=DeploymentStatus.LIVE)
            session.add(deployment)
            session.commit()
            instance = Instance(
                deployment_id=deployment.id,
                node_id=node.id,
                container_id="0123456789ab",
                status=ModelInstanceStatus.UNREACHABLE,
            )
            session.add(instance)
            session.commit()

            process_heartbeat(
                session,
                "node-a",
                [
                    ContainerState(
                        id="0123456789ab" + "c" * 52,
                        name="rudder-app-a",
                        status=InstanceStatus.STARTING,
                        docker_status="running",
                    )
                ],
            )

            session.refresh(instance)
            assert instance.status == ModelInstanceStatus.HEALTHY
            session.refresh(node)
            assert node.cpu_allocated == 0
            assert node.memory_allocated_mb == 0
    finally:
        SQLModel.metadata.drop_all(engine)


@pytest.mark.asyncio
async def test_list_nodes_includes_instances_without_duplicate_schema_fields() -> None:
    """Regression test for the authenticated dashboard's GET /nodes response."""
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            session.add(Node(hostname="node-a", ip_address="10.42.0.4"))
            session.commit()

            response = await list_nodes(session, object())

            assert len(response) == 1
            assert response[0].hostname == "node-a"
            assert response[0].instances == []
    finally:
        SQLModel.metadata.drop_all(engine)
