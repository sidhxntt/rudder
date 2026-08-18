"""Bounded runtime-log persistence and SSE tail behaviour."""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest
from sqlmodel import Session, SQLModel, create_engine

import rudder_cp.services.runtime_logs as runtime_logs_service
from rudder_cp.config import Settings
from rudder_cp.logs.runtime import ACTIVE_BYTES, RuntimeLogStore
from rudder_cp.models import (
    Deployment,
    DeploymentStatus,
    Environment,
    GitHubImport,
    GitHubImportService,
    Instance,
    InstanceStatus,
    Node,
    Project,
    Service,
    User,
)
from rudder_cp.services.agent_client import RuntimeLogSnapshot
from rudder_cp.services.runtime_logs import collect_runtime_logs


async def test_snapshots_deduplicate_and_tail_new_data(tmp_path: Path) -> None:
    store = RuntimeLogStore(tmp_path)
    service_id = uuid4()
    assert await store.append_snapshot(service_id, "one\\ntwo\\n") == len("one\\ntwo\\n")
    assert await store.append_snapshot(service_id, "two\\nthree\\n") == len("three\\n")

    events = store.tail(service_id, poll_interval=0.01)
    first = await asyncio.wait_for(anext(events), 1)
    assert first.text == "one\\ntwo\\nthree\\n"
    await store.append_snapshot(service_id, "three\\nfour\\n")
    second = await asyncio.wait_for(anext(events), 1)
    assert second.text == "four\\n"
    await events.aclose()


async def test_runtime_snapshot_returns_collected_data_without_following(tmp_path: Path) -> None:
    store = RuntimeLogStore(tmp_path)
    service_id = uuid4()
    await store.append_snapshot(service_id, "one\\ntwo\\n")

    assert await store.snapshot(service_id) == "one\\ntwo\\n"


async def test_log_flood_rotates_at_fixed_cap(tmp_path: Path) -> None:
    store = RuntimeLogStore(tmp_path)
    service_id = uuid4()
    await store.append_snapshot(service_id, "a" * ACTIVE_BYTES)
    await store.append_snapshot(service_id, "a" * ACTIVE_BYTES + "b")

    active = store.path_for(service_id)
    archive = active.with_suffix(".log.1")
    assert 0 < active.stat().st_size <= ACTIVE_BYTES
    assert archive.stat().st_size == ACTIVE_BYTES


async def test_agent_drop_is_visible_in_persisted_log(tmp_path: Path) -> None:
    store = RuntimeLogStore(tmp_path)
    service_id = uuid4()
    await store.append_snapshot(service_id, "hello\\n", dropped_bytes=42)
    assert "dropped 42 log bytes" in store.path_for(service_id).read_text()


def test_runtime_log_paths_reject_non_uuid(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        RuntimeLogStore(tmp_path).path_for("../../etc/passwd")


class _Agent:
    def for_node(self, _ip_address: str) -> "_Agent":
        return self

    async def runtime_logs(self, _container_id: str) -> RuntimeLogSnapshot:
        return RuntimeLogSnapshot(text="worker processed job\\n", dropped_bytes=0)


class _KubernetesLogs:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.closed = False

    async def runtime_logs(self, namespace: str, pod_uid: str) -> RuntimeLogSnapshot:
        self.calls.append((namespace, pod_uid))
        return RuntimeLogSnapshot(text="kubernetes ready\\n", dropped_bytes=0)

    async def close(self) -> None:
        self.closed = True


async def test_imported_compose_member_logs_are_written_to_the_member_service(
    tmp_path: Path,
) -> None:
    """Child service logs must not be hidden under the import owner's service."""
    engine = create_engine(f"sqlite:///{tmp_path / 'runtime-log-collector.db'}")
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            user = User(email="logs@example.test", password_hash="unused")
            session.add(user)
            session.commit()
            project = Project(name="logs", owner_id=user.id)
            session.add(project)
            session.commit()
            environment = Environment(project_id=project.id, name="production")
            session.add(environment)
            session.commit()
            app = Service(environment_id=environment.id, name="app")
            worker = Service(environment_id=environment.id, name="worker")
            node = Node(hostname="local", ip_address="127.0.0.1")
            session.add_all([app, worker, node])
            session.commit()
            imported = GitHubImport(
                installation_id=1,
                repository="acme/logs",
                branch="main",
                compose_source="generated",
                compose_manifest="services: {}",
                compose_project_name="logs-test",
                project_id=project.id,
                app_service_id=app.id,
            )
            session.add(imported)
            session.commit()
            session.add(
                GitHubImportService(
                    github_import_id=imported.id,
                    service_id=worker.id,
                    compose_service="worker",
                    role="worker",
                )
            )
            deployment = Deployment(service_id=app.id, status=DeploymentStatus.LIVE)
            session.add(deployment)
            session.commit()
            session.add(
                Instance(
                    deployment_id=deployment.id,
                    node_id=node.id,
                    container_id="worker-container",
                    compose_service="worker",
                    status=InstanceStatus.HEALTHY,
                )
            )
            session.commit()
            app_id, worker_id = app.id, worker.id

        store = RuntimeLogStore(tmp_path / "runtime-logs")
        with Session(engine) as session:
            written = await collect_runtime_logs(
                session,
                _Agent(),  # type: ignore[arg-type]
                Settings(secret_keys="", runtime="docker"),
                store,
            )

        assert written == len("worker processed job\\n")
        assert store.path_for(worker_id).read_text() == "worker processed job\\n"
        assert not store.exists(app_id)
    finally:
        SQLModel.metadata.drop_all(engine)


async def test_kubernetes_runtime_logs_are_collected_without_a_node_agent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'kubernetes-runtime-log-collector.db'}")
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            user = User(email="kubernetes-logs@example.test", password_hash="unused")
            session.add(user)
            session.commit()
            project = Project(name="kubernetes-logs", owner_id=user.id)
            session.add(project)
            session.commit()
            environment = Environment(project_id=project.id, name="production")
            session.add(environment)
            node = Node(hostname="platform", ip_address="10.0.0.1")
            service = Service(environment_id=environment.id, name="app")
            session.add_all([environment, node, service])
            session.commit()
            deployment = Deployment(service_id=service.id, status=DeploymentStatus.LIVE)
            session.add(deployment)
            session.commit()
            session.add(
                Instance(
                    deployment_id=deployment.id,
                    node_id=node.id,
                    container_id="pod-uid",
                    status=InstanceStatus.HEALTHY,
                )
            )
            session.commit()
            service_id = service.id
            namespace = f"rudder-{environment.id.hex[:12]}"

        kubernetes = _KubernetesLogs()

        async def load_client(_settings: Settings) -> _KubernetesLogs:
            return kubernetes

        monkeypatch.setattr(runtime_logs_service, "load_kubernetes_client", load_client)
        store = RuntimeLogStore(tmp_path / "runtime-logs")
        with Session(engine) as session:
            written = await collect_runtime_logs(
                session,
                _Agent(),  # type: ignore[arg-type]
                Settings(secret_keys="", runtime="kubernetes"),
                store,
            )

        assert written == len("kubernetes ready\\n")
        assert kubernetes.calls == [(namespace, "pod-uid")]
        assert kubernetes.closed
        assert store.path_for(service_id).read_text() == "kubernetes ready\\n"
    finally:
        SQLModel.metadata.drop_all(engine)
