"""Deploy-path tests, including the concurrency test D14 requires.

There is no scheduler until Phase 2, so D14 points the required concurrency test
at the deploy path instead.

Caveat stated up front: the real D11 mechanism is a Postgres advisory lock, and
these tests run on SQLite, which has none. They exercise the in-process fallback
in locks.py. That fallback shares the *shape* of the real thing — try-acquire,
no blocking, released on exit — but a test passing here does NOT prove the
Postgres path works. Re-run this file against Postgres once a database is up.
"""

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from rudder_cp.config import Settings
from rudder_cp.models import (
    Deployment,
    DeploymentStatus,
    Environment,
    GitHubImport,
    Instance,
    InstanceStatus,
    Project,
    Service,
    User,
    Volume,
)
from rudder_cp.services import locks
from rudder_cp.services.agent_client import (
    AgentError,
    ComposeResult,
    ComposeServiceState,
    ContainerState,
    ProbeResult,
)
from rudder_cp.services.builder import BuildFailed, BuildResult
from rudder_cp.services.deploy import run_deployment


@pytest.fixture(autouse=True)
def _clean_locks():
    locks._reset_fallback_locks()
    yield
    locks._reset_fallback_locks()


@pytest.fixture
def engine(tmp_path):
    # A file-backed SQLite database, not in-memory: the deploy path opens more
    # than one session and they must see each other's writes.
    engine = create_engine(f"sqlite:///{tmp_path/'test.db'}")
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        secret_keys="",
        traefik_dynamic_dir=str(tmp_path / "dynamic"),
        build_log_dir=str(tmp_path / "logs"),
        health_start_grace_seconds=0,
        health_interval_seconds=0,
        health_timeout_seconds=2,
        drain_seconds=0,
    )


@pytest.fixture
def service(engine) -> Service:
    with Session(engine) as session:
        user = User(email="a@b.c", password_hash="x")
        session.add(user)
        session.commit()
        project = Project(name="shop", owner_id=user.id)
        session.add(project)
        session.commit()
        environment = Environment(project_id=project.id, name="production", is_production=True)
        session.add(environment)
        session.commit()
        svc = Service(
            environment_id=environment.id,
            name="api",
            source_repo="me/shop-api",
            container_port=8080,
            health_check_port=9999,
        )
        session.add(svc)
        session.commit()
        session.refresh(svc)
        return svc


class FakeAgent:
    """Stands in for the node agent. Records what the deploy path asked for."""

    def __init__(
        self,
        *,
        healthy: bool = True,
        alive_after_health: bool = True,
        compose_fails: bool = False,
    ):
        self.healthy = healthy
        self.alive_after_health = alive_after_health
        self.created: list[str] = []
        self.removed: list[str] = []
        self._probe_count = 0
        self.compose_fails = compose_fails
        self.compose_projects: list[str] = []
        self.compose_down_projects: list[str] = []

    async def create_container(self, *, image, name, env, container_port, **_kw) -> ContainerState:
        self.created.append(name)
        self.last_env = env
        self.last_port = container_port
        self.last_create_kwargs = _kw
        self.last_image = image
        return ContainerState(id=f"container-{name}", status="starting", docker_status="running")

    async def inspect(self, container_id: str) -> ContainerState:
        if self._probe_count and not self.alive_after_health:
            return ContainerState(id=container_id, status="stopped", exit_code=1)
        return ContainerState(id=container_id, status="healthy", docker_status="running")

    async def probe(
        self, container_id, *, path, port, timeout_seconds=5.0, protocol="http"
    ) -> ProbeResult:
        self._probe_count += 1
        self.last_protocol = protocol
        if self.healthy:
            return ProbeResult(ok=True, status_code=200, reason=None)
        return ProbeResult(ok=False, status_code=502, reason="connection refused")

    async def remove(self, container_id: str, *, drain_seconds: float) -> None:
        self.removed.append(container_id)

    async def compose_up(self, *, project_name: str, manifest: str) -> ComposeResult:
        if self.compose_fails:
            raise AgentError("compose_error: application exited")
        self.compose_projects.append(project_name)
        self.last_compose_manifest = manifest
        return ComposeResult(project_name=project_name, log="Container app Started\n")

    async def compose_ps(self, *, project_name: str) -> list[ComposeServiceState]:
        return [
            ComposeServiceState(
                service="app",
                container_id=f"compose-{project_name}",
                status="running",
                health="healthy",
                exit_code=None,
            )
        ]

    async def compose_down(self, *, project_name: str) -> ComposeResult:
        self.compose_down_projects.append(project_name)
        return ComposeResult(project_name=project_name, log="Container app Removed\n")


@dataclass
class SlowBuilder:
    """A build that takes measurable time, so two deploys genuinely overlap."""

    delay: float = 0.05
    started: int = 0

    async def __call__(self, request, store, settings) -> BuildResult:
        self.started += 1
        await asyncio.sleep(self.delay)
        return BuildResult(image_tag=f"registry/{request.service_id}:sha", commit_sha="sha")


async def _ok_builder(request, store, settings) -> BuildResult:
    return BuildResult(image_tag=f"registry/{request.service_id}:abc123", commit_sha="abc123")


async def _failing_builder(request, store, settings):
    raise BuildFailed("npm install exited 1")


def _queue(engine, service_id) -> uuid.UUID:
    with Session(engine) as session:
        deployment = Deployment(service_id=service_id, status=DeploymentStatus.QUEUED)
        session.add(deployment)
        session.commit()
        return deployment.id


async def _run(engine, deployment_id, agent, settings, builder, store=None):
    from rudder_cp.logs.store import BuildLogStore

    with Session(engine) as session:
        return await run_deployment(
            deployment_id,
            session=session,
            engine=engine,
            agent=agent,  # type: ignore[arg-type]
            store=store or BuildLogStore(settings.build_log_dir),
            settings=settings,
            builder=builder,
        )


# ------------------------------------------------------------------ happy path


async def test_successful_deploy_goes_live(engine, service, settings):
    agent = FakeAgent()
    outcome = await _run(engine, _queue(engine, service.id), agent, settings, _ok_builder)

    assert outcome.status is DeploymentStatus.LIVE
    with Session(engine) as session:
        deployment = session.get(Deployment, outcome.deployment_id)
        assert deployment.became_live_at is not None
        assert deployment.image_tag.endswith(":abc123")
        instances = session.exec(select(Instance)).all()
        assert [i.status for i in instances] == [InstanceStatus.HEALTHY]


async def test_health_check_probes_health_port_not_container_port(engine, service, settings):
    """container_port routes traffic, health_check_port is probed. D1."""
    agent = FakeAgent()
    probed: list[int] = []
    original = agent.probe

    async def record(container_id, *, path, port, timeout_seconds=5.0):
        probed.append(port)
        return await original(container_id, path=path, port=port)

    agent.probe = record  # type: ignore[method-assign]
    await _run(engine, _queue(engine, service.id), agent, settings, _ok_builder)

    assert probed == [9999]
    assert agent.last_port == 8080


# ------------------------------------------------------------------ failure paths


async def test_failed_build_marks_deployment_failed_with_reason(engine, service, settings):
    agent = FakeAgent()
    outcome = await _run(engine, _queue(engine, service.id), agent, settings, _failing_builder)

    assert outcome.status is DeploymentStatus.FAILED
    with Session(engine) as session:
        failed = session.get(Deployment, outcome.deployment_id)
        assert failed.error_message == "npm install exited 1"
        assert session.exec(select(Instance)).all() == []
    assert agent.created == []


async def test_failed_deploy_leaves_previous_version_serving(engine, service, settings):
    """The core promise: a failed deploy is a no-op from the user's perspective."""
    first = await _run(engine, _queue(engine, service.id), FakeAgent(), settings, _ok_builder)
    assert first.status is DeploymentStatus.LIVE

    second = await _run(engine, _queue(engine, service.id), FakeAgent(), settings, _failing_builder)
    assert second.status is DeploymentStatus.FAILED

    with Session(engine) as session:
        live = session.get(Deployment, first.deployment_id)
        assert live.status is DeploymentStatus.LIVE
        healthy = session.exec(
            select(Instance).where(Instance.status == InstanceStatus.HEALTHY)
        ).all()
        assert len(healthy) == 1
        assert healthy[0].deployment_id == first.deployment_id


async def test_imported_compose_failure_keeps_the_previous_release_live(
    engine, service, settings
):
    """Candidate Compose projects are isolated until their app is healthy."""
    with Session(engine) as session:
        app = session.get(Service, service.id)
        assert app is not None
        environment = session.get(Environment, app.environment_id)
        assert environment is not None
        app.build_config = {"compose_service": "app", "managed_image": "nginx:alpine"}
        session.add(app)
        session.add(
            GitHubImport(
                installation_id=7,
                repository="acme/shop-api",
                branch="main",
                compose_source="generated",
                compose_manifest="services:\n  app:\n    build: .\n    expose: ['8080']\n",
                compose_project_name="rudder-compose-test",
                project_id=environment.project_id,
                app_service_id=app.id,
            )
        )
        session.commit()

    first_agent = FakeAgent()
    first = await _run(engine, _queue(engine, service.id), first_agent, settings, _ok_builder)
    failed = await _run(
        engine, _queue(engine, service.id), FakeAgent(compose_fails=True), settings, _ok_builder
    )

    assert first.status is DeploymentStatus.LIVE
    assert failed.status is DeploymentStatus.FAILED
    assert first_agent.compose_projects
    with Session(engine) as session:
        assert session.get(Deployment, first.deployment_id).status is DeploymentStatus.LIVE
        healthy = session.exec(
            select(Instance).where(Instance.deployment_id == first.deployment_id)
        ).one()
        assert healthy.status is InstanceStatus.HEALTHY


async def test_unhealthy_container_is_removed_and_deploy_fails(engine, service, settings):
    agent = FakeAgent(healthy=False)
    outcome = await _run(engine, _queue(engine, service.id), agent, settings, _ok_builder)

    assert outcome.status is DeploymentStatus.FAILED
    assert "did not pass" in (outcome.detail or "")
    assert agent.removed == ["container-" + agent.created[0]]


async def test_container_dying_between_health_check_and_shift_fails_the_deploy(
    engine, service, settings
):
    """The race the phase doc names: 200, then dead, then the traffic shift."""
    agent = FakeAgent(healthy=True, alive_after_health=False)
    outcome = await _run(engine, _queue(engine, service.id), agent, settings, _ok_builder)

    assert outcome.status is DeploymentStatus.FAILED
    with Session(engine) as session:
        assert session.exec(select(Instance)).first().status is InstanceStatus.STOPPED


async def test_agent_failure_is_a_readable_error_not_a_traceback(engine, service, settings):
    agent = FakeAgent()

    async def boom(**_kw):
        raise AgentError("422: image_pull_failed")

    agent.create_container = boom  # type: ignore[method-assign]
    outcome = await _run(engine, _queue(engine, service.id), agent, settings, _ok_builder)

    assert outcome.status is DeploymentStatus.FAILED
    assert "image_pull_failed" in (outcome.detail or "")


# ------------------------------------------------------------------ rolling deploy


async def test_second_deploy_drains_the_first(engine, service, settings):
    first = await _run(engine, _queue(engine, service.id), FakeAgent(), settings, _ok_builder)
    agent = FakeAgent()
    second = await _run(engine, _queue(engine, service.id), agent, settings, _ok_builder)

    assert second.status is DeploymentStatus.LIVE
    with Session(engine) as session:
        instances = {i.deployment_id: i for i in session.exec(select(Instance)).all()}
        assert instances[first.deployment_id].status is InstanceStatus.STOPPED
        assert instances[first.deployment_id].stopped_at is not None
        assert instances[second.deployment_id].status is InstanceStatus.HEALTHY
        # Exactly one Deployment is `live` afterwards.
        assert session.get(Deployment, first.deployment_id).status is DeploymentStatus.SUPERSEDED
    assert len(agent.removed) == 1


# ------------------------------------------------------------------ D14: concurrency


async def test_concurrent_deploys_produce_exactly_one_live_instance(engine, service, settings):
    """Two deploys launched together. D11/D14.

    The lock is try-acquire, so the loser stays queued rather than blocking a
    worker. Running the loser again afterwards is what a real worker tick does.
    """
    builder = SlowBuilder(delay=0.05)
    agent_a, agent_b = FakeAgent(), FakeAgent()
    first, second = _queue(engine, service.id), _queue(engine, service.id)

    outcomes = await asyncio.gather(
        _run(engine, first, agent_a, settings, builder),
        _run(engine, second, agent_b, settings, builder),
    )
    statuses = [o.status for o in outcomes]

    assert statuses.count(DeploymentStatus.LIVE) == 1
    assert statuses.count(DeploymentStatus.QUEUED) == 1
    # The loser never built. That is the point of the lock: no two builds race.
    assert builder.started == 1

    loser_id = next(o.deployment_id for o in outcomes if o.status is DeploymentStatus.QUEUED)
    winner_id = next(o.deployment_id for o in outcomes if o.status is DeploymentStatus.LIVE)

    retry = await _run(engine, loser_id, FakeAgent(), settings, builder)
    assert retry.status is DeploymentStatus.LIVE

    with Session(engine) as session:
        healthy = session.exec(
            select(Instance).where(Instance.status == InstanceStatus.HEALTHY)
        ).all()
        assert len(healthy) == 1, "exactly one live instance"
        assert healthy[0].deployment_id == loser_id
        # The newer push wins in the end, and only one Deployment is `live`.
        assert session.get(Deployment, winner_id).status is DeploymentStatus.SUPERSEDED
        live = session.exec(
            select(Deployment).where(Deployment.status == DeploymentStatus.LIVE)
        ).all()
        assert [d.id for d in live] == [loser_id]


async def test_a_newer_queued_deploy_is_never_superseded_by_an_older_one(engine, service, settings):
    """The newest push must win. Superseding by "not me" instead of "older than
    me" would silently drop it and leave stale code live."""
    older = _queue(engine, service.id)
    newer = _queue(engine, service.id)

    await _run(engine, older, FakeAgent(), settings, _ok_builder)

    with Session(engine) as session:
        assert session.get(Deployment, newer).status is DeploymentStatus.QUEUED

    outcome = await _run(engine, newer, FakeAgent(), settings, _ok_builder)
    assert outcome.status is DeploymentStatus.LIVE


async def test_older_in_flight_deployments_are_superseded(engine, service, settings):
    stale = _queue(engine, service.id)
    with Session(engine) as session:
        deployment = session.get(Deployment, stale)
        deployment.status = DeploymentStatus.BUILDING
        deployment.created_at = datetime.now(UTC)
        session.add(deployment)
        session.commit()

    current = await _run(engine, _queue(engine, service.id), FakeAgent(), settings, _ok_builder)

    assert current.status is DeploymentStatus.LIVE
    with Session(engine) as session:
        assert session.get(Deployment, stale).status is DeploymentStatus.SUPERSEDED


async def test_a_non_queued_deployment_is_not_run_twice(engine, service, settings):
    deployment_id = _queue(engine, service.id)
    await _run(engine, deployment_id, FakeAgent(), settings, _ok_builder)

    builder = SlowBuilder()
    again = await _run(engine, deployment_id, FakeAgent(), settings, builder)

    assert again.detail == "not queued"
    assert builder.started == 0


async def test_managed_addon_uses_an_image_volume_alias_and_tcp_readiness(
    engine, service, settings
):
    """Managed infrastructure bypasses BuildKit but stays private and durable."""
    with Session(engine) as session:
        managed = session.get(Service, service.id)
        assert managed is not None
        managed.name = "redis"
        managed.source_repo = None
        managed.container_port = 6379
        managed.health_check_port = 6379
        managed.build_config = {
            "managed_image": "redis:7-alpine",
            "command": ["redis-server", "--requirepass", "secret"],
        }
        session.add(managed)
        session.flush()
        session.add(Volume(service_id=managed.id, mount_path="/data"))
        session.commit()

    async def should_not_build(*_args, **_kwargs):
        raise AssertionError("managed images must not go through BuildKit")

    agent = FakeAgent()
    outcome = await _run(engine, _queue(engine, service.id), agent, settings, should_not_build)

    assert outcome.status is DeploymentStatus.LIVE
    assert agent.last_image == "redis:7-alpine"
    assert agent.last_protocol == "tcp"
    assert agent.last_create_kwargs["network_aliases"] == ["redis"]
    assert list(agent.last_create_kwargs["volumes"].values()) == [
        {"bind": "/data", "mode": "rw"}
    ]
    assert agent.last_create_kwargs["command"] == ["redis-server", "--requirepass", "secret"]


async def test_managed_addon_has_a_completed_lifecycle_log(engine, service, settings):
    with Session(engine) as session:
        managed = session.get(Service, service.id)
        assert managed is not None
        managed.name = "postgres"
        managed.source_repo = None
        managed.container_port = 5432
        managed.health_check_port = 5432
        managed.build_config = {"managed_image": "postgres:16-alpine"}
        session.add(managed)
        session.commit()

    from rudder_cp.logs.store import BuildLogStore

    store = BuildLogStore(settings.build_log_dir)
    outcome = await _run(
        engine,
        _queue(engine, service.id),
        FakeAgent(),
        settings,
        builder=lambda *_args: (_ for _ in ()).throw(AssertionError("must not build")),
        store=store,
    )

    assert outcome.status is DeploymentStatus.LIVE
    contents = store.path_for(outcome.deployment_id).read_text()
    assert "using managed image postgres:16-alpine" in contents
    assert "starting private service postgres" in contents
    assert "deployment is live" in contents
