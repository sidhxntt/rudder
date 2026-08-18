"""Phase 6 metric retention/downsampling contract."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlmodel import Session, SQLModel, create_engine, select

import rudder_cp.services.metrics as metrics_service
from rudder_cp.config import Settings
from rudder_cp.models import (
    Deployment,
    DeploymentStatus,
    Environment,
    Instance,
    InstanceStatus,
    Node,
    Project,
    RuntimeMetric,
    Service,
    User,
)
from rudder_cp.services.agent_client import ContainerMetrics
from rudder_cp.services.metrics import (
    FIVE_MINUTE_SECONDS,
    MINUTE_SECONDS,
    RAW_SECONDS,
    collect_runtime_metrics,
    compact_runtime_metrics,
)


def test_metrics_roll_up_and_expire_without_unbounded_raw_rows() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    instance_id = uuid4()
    now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    with Session(engine) as session:
        # Old raw samples become one-minute aggregates; anything older than
        # seven days disappears after it has had a chance to roll up.
        for offset in range(0, 60, 10):
            session.add(
                RuntimeMetric(
                    instance_id=instance_id,
                    captured_at=now - timedelta(hours=2) + timedelta(seconds=offset),
                    resolution_seconds=RAW_SECONDS,
                    cpu_percent=10 + offset,
                    memory_bytes=1000 + offset,
                )
            )
        session.add(
            RuntimeMetric(
                instance_id=instance_id,
                captured_at=now - timedelta(days=8),
                resolution_seconds=FIVE_MINUTE_SECONDS,
                cpu_percent=1,
                memory_bytes=1,
            )
        )
        session.commit()

        assert compact_runtime_metrics(session, now=now) >= 1
        remaining = session.exec(select(RuntimeMetric)).all()
    assert not [row for row in remaining if row.resolution_seconds == RAW_SECONDS]
    assert any(row.resolution_seconds == MINUTE_SECONDS for row in remaining)
    assert not [row for row in remaining if row.resolution_seconds == FIVE_MINUTE_SECONDS]


class _KubernetesMetrics:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    async def runtime_metrics(self, namespace: str, pod_uid: str) -> ContainerMetrics:
        self.calls.append((namespace, pod_uid))
        return ContainerMetrics(cpu_percent=12.5, memory_bytes=8192)

    async def close(self) -> None:
        self.closed = True


class _Agent:
    def for_node(self, _ip_address: str) -> "_Agent":
        return self

    async def runtime_metrics(self, _container_id: str) -> ContainerMetrics:
        raise AssertionError("the Docker agent must not be used for Kubernetes metrics")


async def test_kubernetes_runtime_metrics_are_collected_without_a_node_agent(
    tmp_path, monkeypatch
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'kubernetes-metrics.db'}")
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            user = User(email="kubernetes-metrics@example.test", password_hash="unused")
            project = Project(name="kubernetes-metrics", owner_id=user.id)
            environment = Environment(project_id=project.id, name="production")
            node = Node(hostname="platform", ip_address="10.0.0.1")
            session.add_all([user, project, environment, node])
            session.commit()
            service = Service(environment_id=environment.id, name="app")
            session.add(service)
            session.commit()
            deployment = Deployment(service_id=service.id, status=DeploymentStatus.LIVE)
            session.add(deployment)
            session.commit()
            instance = Instance(
                deployment_id=deployment.id,
                node_id=node.id,
                container_id="pod-uid",
                status=InstanceStatus.HEALTHY,
            )
            session.add(instance)
            session.commit()
            namespace = f"rudder-{environment.id.hex[:12]}"

        kubernetes = _KubernetesMetrics()

        async def load_client(_settings: Settings) -> _KubernetesMetrics:
            return kubernetes

        monkeypatch.setattr(metrics_service, "load_kubernetes_client", load_client)
        with Session(engine) as session:
            added = await collect_runtime_metrics(
                session,
                _Agent(),  # type: ignore[arg-type]
                Settings(secret_keys="", runtime="kubernetes"),
            )
            samples = session.exec(select(RuntimeMetric)).all()

        assert added == 1
        assert kubernetes.calls == [(namespace, "pod-uid")]
        assert kubernetes.closed
        assert len(samples) == 1
        assert samples[0].cpu_percent == 12.5
        assert samples[0].memory_bytes == 8192
    finally:
        SQLModel.metadata.drop_all(engine)
