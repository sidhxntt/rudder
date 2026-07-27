"""Instance reconciliation tests.

The behaviour under test is the one the live stack exposed: `docker kill` a
container and the database keeps claiming `healthy` while Traefik routes to a
corpse.
"""

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from rudder_cp.config import Settings
from rudder_cp.models import (
    Deployment,
    DeploymentStatus,
    Domain,
    DomainTargetType,
    Environment,
    Instance,
    InstanceStatus,
    Node,
    Project,
    Service,
    User,
)
from rudder_cp.services.agent_client import AgentError, ContainerState
from rudder_cp.services.monitor import reconcile_instances


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'monitor.db'}")
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(secret_keys="", traefik_dynamic_dir=str(tmp_path / "dynamic"))


@pytest.fixture
def live(engine):
    """A live deployment with one healthy instance and a system domain."""
    with Session(engine) as session:
        user = User(email="a@b.c", password_hash="x")
        session.add(user)
        session.commit()
        project = Project(name="shop", owner_id=user.id)
        session.add(project)
        session.commit()
        environment = Environment(project_id=project.id, name="production")
        session.add(environment)
        session.commit()
        service = Service(environment_id=environment.id, name="api", container_port=3000)
        node = Node(hostname="localhost", ip_address="127.0.0.1")
        session.add(service)
        session.add(node)
        session.commit()
        deployment = Deployment(service_id=service.id, status=DeploymentStatus.LIVE)
        session.add(deployment)
        session.commit()
        instance = Instance(
            deployment_id=deployment.id,
            node_id=node.id,
            container_id="abcdef123456",
            status=InstanceStatus.HEALTHY,
        )
        domain = Domain(
            hostname="api.production.localhost",
            environment_id=environment.id,
            target_type=DomainTargetType.SERVICE,
            service_id=service.id,
            is_system=True,
        )
        session.add(instance)
        session.add(domain)
        session.commit()
        return {"instance_id": instance.id, "domain_id": domain.id}


class FakeAgent:
    def __init__(self, status: str | None = "healthy", error: Exception | None = None):
        self.status = status
        self.error = error
        self.calls = 0

    def for_node(self, ip_address: str) -> "FakeAgent":
        del ip_address
        return self

    async def inspect(self, container_id: str) -> ContainerState:
        self.calls += 1
        if self.error:
            raise self.error
        return ContainerState(id=container_id, status=self.status or "healthy")


async def test_killed_container_is_recorded_as_stopped(engine, settings, live):
    agent = FakeAgent(status="stopped")
    changed = await reconcile_instances(Session(engine), agent, settings)  # type: ignore[arg-type]

    assert changed == 1
    with Session(engine) as session:
        assert session.get(Instance, live["instance_id"]).status is InstanceStatus.STOPPED


async def test_routing_is_regenerated_when_state_changes(engine, settings, live):
    agent = FakeAgent(status="stopped")
    await reconcile_instances(Session(engine), agent, settings)  # type: ignore[arg-type]

    dynamic_dir = _dir(settings)
    router_files = sorted(dynamic_dir.glob("*.yml"))
    assert router_files, "a router file should have been written"
    contents = router_files[0].read_text()
    assert "abcdef123456" not in contents, "a dead instance must leave the backend"


async def test_reconciliation_is_idempotent(engine, settings, live):
    """Running twice changes nothing the second time, and does not re-render."""
    agent = FakeAgent(status="healthy")
    assert await reconcile_instances(Session(engine), agent, settings) == 0  # type: ignore[arg-type]
    assert await reconcile_instances(Session(engine), agent, settings) == 0  # type: ignore[arg-type]


async def test_an_unreachable_agent_does_not_take_a_service_out_of_rotation(
    engine, settings, live
):
    """Uncertainty is not evidence of death. A network blip must not deroute."""
    agent = FakeAgent(error=AgentError("Node agent unreachable at http://agent:9000"))
    changed = await reconcile_instances(Session(engine), agent, settings)  # type: ignore[arg-type]

    assert changed == 0
    with Session(engine) as session:
        assert session.get(Instance, live["instance_id"]).status is InstanceStatus.HEALTHY


async def test_a_missing_container_is_evidence_of_death(engine, settings, live):
    agent = FakeAgent(error=AgentError("container_not_found: no such container"))
    changed = await reconcile_instances(Session(engine), agent, settings)  # type: ignore[arg-type]

    assert changed == 1
    with Session(engine) as session:
        assert session.get(Instance, live["instance_id"]).status is InstanceStatus.STOPPED


async def test_instances_of_non_live_deployments_are_left_alone(engine, settings, live):
    """The deploy path owns in-flight instances; the monitor must not race it."""
    with Session(engine) as session:
        deployment = session.exec(select(Deployment)).one()
        deployment.status = DeploymentStatus.DEPLOYING
        session.add(deployment)
        session.commit()

    agent = FakeAgent(status="stopped")
    assert await reconcile_instances(Session(engine), agent, settings) == 0  # type: ignore[arg-type]
    assert agent.calls == 0


def _dir(settings: Settings):
    from pathlib import Path

    return Path(settings.traefik_dynamic_dir)
