
import asyncio
import threading
import uuid

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from rudder_cp.models import Node, NodeStatus, Service
from rudder_cp.services.scheduler import select_node_for_service


@pytest.fixture(name="engine")
def engine_fixture():
    # Note: The scheduler's FOR UPDATE lock is not supported by SQLite.
    # These tests will pass if the logic is correct, but they cannot
    # fully guarantee race condition prevention without running against
    # a database like PostgreSQL. The concurrency test is expected to fail
    # on SQLite as it will expose the race condition.
    engine = create_engine(
        "sqlite:///file:memdb1?mode=memory&cache=shared&uri=true",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session


def test_select_node_for_service_success(session: Session):
    # Healthy node with plenty of capacity
    node1 = Node(
        hostname="node1",
        ip_address="192.168.1.1",
        status=NodeStatus.HEALTHY,
        cpu_total=4.0,
        cpu_allocated=1.0,
        memory_total_mb=8192,
        memory_allocated_mb=2048,
    )
    # Healthy node with less memory capacity (higher utilization)
    node2 = Node(
        hostname="node2",
        ip_address="192.168.1.2",
        status=NodeStatus.HEALTHY,
        cpu_total=4.0,
        cpu_allocated=1.0,
        memory_total_mb=8192,
        memory_allocated_mb=6144,
    )
    # A non-healthy node that should be ignored
    node3 = Node(
        hostname="node3",
        ip_address="192.168.1.3",
        status=NodeStatus.UNREACHABLE,
        cpu_total=16.0,
        cpu_allocated=0,
        memory_total_mb=32768,
        memory_allocated_mb=0,
    )
    session.add_all([node1, node2, node3])
    session.commit()
    session.refresh(node1)
    session.refresh(node2)
    session.refresh(node3)


    service = Service(
        name="test-service",
        cpu_limit=1.0,
        memory_limit_mb=1024,
        container_port=80,
        environment_id=uuid.uuid4()
    )

    selected_node = select_node_for_service(session, service)


    # Should select node1 as it has the lowest memory utilization ratio
    # node1 utilization: 2048 / 8192 = 0.25
    # node2 utilization: 6144 / 8192 = 0.75
    assert selected_node.id == node1.id


def test_select_node_for_service_no_capacity(session: Session):
    # Node with insufficient CPU
    node1 = Node(
        hostname="node1",
        ip_address="192.168.1.1",
        status=NodeStatus.HEALTHY,
        cpu_total=2.0,
        cpu_allocated=1.5,
        memory_total_mb=8192,
        memory_allocated_mb=2048,
    )
    # Node with insufficient memory
    node2 = Node(
        hostname="node2",
        ip_address="192.168.1.2",
        status=NodeStatus.HEALTHY,
        cpu_total=4.0,
        cpu_allocated=1.0,
        memory_total_mb=8192,
        memory_allocated_mb=7500,
    )
    session.add_all([node1, node2])
    session.commit()

    service = Service(
        name="test-service",
        cpu_limit=1.0,
        memory_limit_mb=1024,
        container_port=80,
        environment_id=uuid.uuid4()
    )

    with pytest.raises(Exception, match="No nodes with sufficient capacity available."):
        select_node_for_service(session, service)


def test_select_node_for_service_concurrency(engine):
    """
    Verify that the `FOR UPDATE` lock prevents race conditions on PostgreSQL.

    SQLite deliberately ignores ``SELECT ... FOR UPDATE``; running this test
    against the local SQLite fixture would only assert a database limitation,
    not scheduler behaviour.
    """
    if engine.dialect.name == "sqlite":
        pytest.skip("row-level locking is only verified against PostgreSQL")
    node = Node(
        hostname="single-node",
        ip_address="192.168.1.1",
        status=NodeStatus.HEALTHY,
        cpu_total=2.0,
        cpu_allocated=0.0,
        memory_total_mb=2048,
        memory_allocated_mb=0,
    )
    with Session(engine) as session:
        session.add(node)
        session.commit()
        session.refresh(node)

    service1 = Service(
        name="service1",
        cpu_limit=1.5,
        memory_limit_mb=1500,
        container_port=80,
        environment_id=uuid.uuid4()
    )
    service2 = Service(
        name="service2",
        cpu_limit=1.5,
        memory_limit_mb=1500,
        container_port=80,
        environment_id=uuid.uuid4()
    )

    results = []

    def allocate_service_to_node(service: Service):
        try:
            with Session(engine) as session:
                selected_node = select_node_for_service(session, service)

                selected_node.cpu_allocated += service.cpu_limit
                selected_node.memory_allocated_mb += service.memory_limit_mb

                session.add(selected_node)
                session.commit()

                results.append(service.name)
        except Exception as e:
            results.append(e)

    thread1 = threading.Thread(target=allocate_service_to_node, args=(service1,))
    thread2 = threading.Thread(target=allocate_service_to_node, args=(service2,))

    thread1.start()
    thread2.start()

    thread1.join()
    thread2.join()

    successful_allocations = [res for res in results if isinstance(res, str)]

    # On a database with proper FOR UPDATE support, this will be 1.
    # On SQLite, it will be 2, demonstrating the race condition.
    if len(successful_allocations) != 1:
        pytest.fail(
            "Race condition detected: "
            f"{len(successful_allocations)} services were scheduled instead of 1."
        )


@pytest.mark.asyncio
async def test_select_node_for_service_concurrency_async(engine):
    """
    Verify that the `FOR UPDATE` lock prevents race conditions with asyncio
    on PostgreSQL.
    """
    if engine.dialect.name == "sqlite":
        pytest.skip("row-level locking is only verified against PostgreSQL")
    node = Node(
        hostname="single-node-async",
        ip_address="192.168.1.1",
        status=NodeStatus.HEALTHY,
        cpu_total=2.0,
        cpu_allocated=0.0,
        memory_total_mb=2048,
        memory_allocated_mb=0,
    )
    with Session(engine) as session:
        session.add(node)
        session.commit()
        session.refresh(node)

    service1 = Service(
        name="service1",
        cpu_limit=1.5,
        memory_limit_mb=1500,
        container_port=80,
        environment_id=uuid.uuid4()
    )
    service2 = Service(
        name="service2",
        cpu_limit=1.5,
        memory_limit_mb=1500,
        container_port=80,
        environment_id=uuid.uuid4()
    )

    async def allocate_service_to_node(service: Service):
        loop = asyncio.get_event_loop()
        try:
            def sync_task():
                with Session(engine) as session:
                    selected_node = select_node_for_service(session, service)

                    selected_node.cpu_allocated += service.cpu_limit
                    selected_node.memory_allocated_mb += service.memory_limit_mb

                    session.add(selected_node)
                    session.commit()
                    return service.name

            result = await loop.run_in_executor(None, sync_task)
            return result
        except Exception as e:
            return e

    results = await asyncio.gather(
        allocate_service_to_node(service1),
        allocate_service_to_node(service2),
    )

    successful_allocations = [res for res in results if isinstance(res, str)]

    if len(successful_allocations) != 1:
        pytest.fail(
            "Race condition detected: "
            f"{len(successful_allocations)} services were scheduled instead of 1."
        )
