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
from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from rudder_cp.config import Settings
from rudder_cp.models import (
    Deployment,
    DeploymentStatus,
    Domain,
    Environment,
    GitHubImport,
    GitHubImportService,
    Instance,
    InstanceStatus,
    Node,
    NodeStatus,
    Project,
    Service,
    ServiceManagedCapabilities,
    User,
    Volume,
)
from rudder_cp.services import deploy as deploy_service
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
    with Session(engine) as session:
        node = Node(
            hostname="test-node",
            ip_address="127.0.0.1",
            status=NodeStatus.HEALTHY,
            cpu_total=4.0,
            memory_total_mb=8192,
        )
        session.add(node)
        session.commit()
    yield engine
    SQLModel.metadata.drop_all(engine)


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
        compose_services: tuple[str, ...] = ("app",),
    ):
        self.healthy = healthy
        self.alive_after_health = alive_after_health
        self.created: list[str] = []
        self.removed: list[str] = []
        self._probe_count = 0
        self.compose_fails = compose_fails
        self.compose_projects: list[str] = []
        self.compose_down_projects: list[str] = []
        self.compose_services = compose_services

    async def create_container(self, *, image, name, env, container_port, **_kw) -> ContainerState:
        self.created.append(name)
        self.last_env = env
        self.last_port = container_port
        self.last_create_kwargs = _kw
        self.last_image = image
        return ContainerState(id=f"container-{name}", status="starting", docker_status="running")

    def for_node(self, ip_address: str, *, port: int = 9000) -> "FakeAgent":
        self.selected_nodes = getattr(self, "selected_nodes", []) + [f"{ip_address}:{port}"]
        return self

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
                service=service,
                container_id=f"compose-{project_name}-{service}",
                status="running",
                health="healthy",
                exit_code=None,
            )
            for service in self.compose_services
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


class FakeKubernetesApi:
    """Records the real imported-deploy dispatch without requiring a cluster."""

    def __init__(self, *, fail_service: str | None = None) -> None:
        self.fail_service = fail_service
        self.calls: list[tuple[str, str]] = []
        self.public_routes: dict[str, str] = {}
        self.workloads: dict[str, object] = {}
        self.closed = False

    async def ensure_namespace(self, namespace: str, _labels: dict[str, str]) -> None:
        self.calls.append(("namespace", namespace))

    async def ensure_guardrails(self, namespace: str, _labels: dict[str, str]) -> None:
        self.calls.append(("guardrails", namespace))

    async def apply_service(self, namespace: str, spec) -> None:
        self.calls.append(("service", spec.name))

    async def apply_workload(self, namespace: str, spec) -> None:
        self.calls.append(("workload", spec.name))
        self.workloads[spec.service_name] = spec

    async def apply_cloudnative_postgres(self, namespace: str, spec) -> None:
        self.calls.append(("cloudnative-postgres", spec.name))
        self.workloads[spec.service_name] = spec

    async def apply_autoscaler(self, namespace: str, spec) -> None:
        self.calls.append(("autoscaler", spec.name))

    async def delete_autoscaler(self, namespace: str, name: str) -> None:
        self.calls.append(("delete-autoscaler", name))

    async def apply_cron_job(self, namespace: str, spec) -> None:
        self.calls.append(("cronjob", spec.name))

    async def delete_cron_jobs_for_workload(
        self, namespace: str, *, workload_name: str, release_id: str
    ) -> None:
        self.calls.append(("delete-cronjobs", workload_name))

    async def apply_job(self, namespace: str, spec) -> None:
        self.calls.append(("job", spec.name))

    async def wait_job_complete(self, namespace: str, spec, **_kwargs) -> bool:
        self.calls.append(("job-complete", spec.name))
        return True

    async def wait_ready(self, namespace: str, spec, **_kwargs) -> str:
        self.calls.append(("ready", spec.name))
        if spec.service_name == self.fail_service:
            raise RuntimeError(f"{spec.service_name} image pull failed")
        return f"pod-{spec.name}"

    async def wait_cloudnative_postgres_ready(self, namespace: str, spec, **_kwargs) -> str:
        self.calls.append(("cloudnative-postgres-ready", spec.name))
        if spec.service_name == self.fail_service:
            raise RuntimeError(f"{spec.service_name} image pull failed")
        return f"pod-{spec.name}-1"

    async def promote_public_service(self, namespace: str, spec) -> None:
        self.calls.append(("ingress", spec.name))
        self.public_routes[spec.name] = spec

    async def delete_release(self, namespace: str, release_id: str) -> None:
        self.calls.append(("cleanup", release_id))

    async def close(self) -> None:
        self.closed = True


def _configure_kubernetes_import(engine, service: Service) -> None:
    """Create the same persisted graph an approved GitHub import produces."""
    with Session(engine) as session:
        app = session.get(Service, service.id)
        assert app is not None
        environment = session.get(Environment, app.environment_id)
        assert environment is not None
        app.build_config = {"compose_service": "app", "managed_image": "nginx:alpine"}
        postgres = Service(
            environment_id=environment.id,
            name="postgres",
            container_port=5432,
            build_config={"compose_service": "postgres"},
        )
        redis = Service(
            environment_id=environment.id,
            name="redis",
            container_port=6379,
            build_config={"compose_service": "redis"},
        )
        session.add_all([app, postgres, redis])
        session.commit()
        session.refresh(postgres)
        session.refresh(redis)
        session.add_all(
            [
                Volume(service_id=postgres.id, mount_path="/var/lib/postgresql/data"),
                Volume(service_id=redis.id, mount_path="/data"),
            ]
        )
        imported = GitHubImport(
            installation_id=7,
            repository="acme/kubernetes-import",
            branch="main",
            compose_source="generated",
            compose_manifest=(
                "services:\n"
                "  app:\n    build: .\n    expose: ['8080']\n"
                "  postgres:\n    image: postgres:16-alpine\n    expose: ['5432']\n"
                "    environment:\n      POSTGRES_PASSWORD: rudder\n"
                "  redis:\n    image: redis:7-alpine\n    expose: ['6379']\n"
            ),
            compose_project_name="rudder-kubernetes-import",
            project_id=environment.project_id,
            app_service_id=app.id,
            postgres_service_id=postgres.id,
            redis_service_id=redis.id,
        )
        session.add(imported)
        session.commit()
        session.add_all(
            [
                GitHubImportService(
                    github_import_id=imported.id,
                    service_id=app.id,
                    compose_service="app",
                    role="web",
                    is_public=True,
                ),
                GitHubImportService(
                    github_import_id=imported.id,
                    service_id=postgres.id,
                    compose_service="postgres",
                    role="database",
                ),
                GitHubImportService(
                    github_import_id=imported.id,
                    service_id=redis.id,
                    compose_service="redis",
                    role="cache",
                ),
            ]
        )
        session.commit()


async def test_imported_kubernetes_uses_cnpg_only_for_catalog_managed_postgres(
    engine, service, settings, monkeypatch
):
    _configure_kubernetes_import(engine, service)
    with Session(engine) as session:
        postgres = session.exec(select(Service).where(Service.name == "postgres")).one()
        session.add(
            ServiceManagedCapabilities(
                service_id=postgres.id,
                database_engine="postgres",
                data_role="primary",
                source="catalog",
            )
        )
        session.commit()

    settings.runtime = "kubernetes"
    api = FakeKubernetesApi()
    _use_kubernetes_api(monkeypatch, api)

    outcome = await _run(engine, _queue(engine, service.id), FakeAgent(), settings, _ok_builder)

    assert outcome.status is DeploymentStatus.LIVE
    assert ("cloudnative-postgres", "postgres") in api.calls
    assert ("cloudnative-postgres-ready", "postgres") in api.calls
    assert "postgres" not in {value for name, value in api.calls if name == "workload"}


def _use_kubernetes_api(monkeypatch, *apis: FakeKubernetesApi) -> None:
    pending = list(apis)

    async def from_kubeconfig(_cls, _settings, *, kubeconfig_path: str = ""):
        assert kubeconfig_path == ""
        return pending.pop(0)

    monkeypatch.setattr(
        deploy_service.AsyncKubernetesApi,
        "from_kubeconfig",
        classmethod(from_kubeconfig),
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


async def test_rollback_reuses_the_immutable_image_without_rebuilding(engine, service, settings):
    """A rollback is a new candidate run of a known-good image, not a rebuild."""
    with Session(engine) as session:
        deployment = Deployment(
            service_id=service.id,
            image_tag="registry/api:known-good",
            commit_sha="known-good",
            status=DeploymentStatus.QUEUED,
        )
        session.add(deployment)
        session.commit()
        deployment_id = deployment.id

    outcome = await _run(engine, deployment_id, FakeAgent(), settings, _failing_builder)

    assert outcome.status is DeploymentStatus.LIVE
    with Session(engine) as session:
        deployed = session.get(Deployment, deployment_id)
        assert deployed is not None
        assert deployed.image_tag == "registry/api:known-good"


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


async def test_imported_kubernetes_release_waits_for_every_member_before_public_promotion(
    engine, service, settings, monkeypatch
):
    """The selected runtime must drive the persisted import graph, not a side path."""
    _configure_kubernetes_import(engine, service)
    settings.runtime = "kubernetes"
    settings.kubernetes_local_domain = "kind.local"
    api = FakeKubernetesApi()
    _use_kubernetes_api(monkeypatch, api)

    outcome = await _run(engine, _queue(engine, service.id), FakeAgent(), settings, _ok_builder)

    assert outcome.status is DeploymentStatus.LIVE
    assert api.closed is True
    assert [name for name, _ in api.calls].count("ready") == 3
    assert [name for name, _ in api.calls].index("ingress") > max(
        index for index, (name, _) in enumerate(api.calls) if name == "ready"
    )
    app_workload = next(
        value for name, value in api.calls if name == "workload" and value.startswith("app-")
    )
    assert api.public_routes["route-app"].backend_service_name == app_workload
    assert api.workloads["postgres"].environment == {"POSTGRES_PASSWORD": "rudder"}
    with Session(engine) as session:
        instances = list(
            session.exec(
                select(Instance).where(Instance.deployment_id == outcome.deployment_id)
            ).all()
        )
        assert {instance.compose_service for instance in instances} == {"app", "postgres", "redis"}
        assert {instance.status for instance in instances} == {InstanceStatus.HEALTHY}
    from rudder_cp.logs.store import BuildLogStore

    contents = BuildLogStore(settings.build_log_dir).path_for(outcome.deployment_id).read_text()
    assert "kubernetes: applying StatefulSet for postgres" in contents
    assert "kubernetes: postgres is ready" in contents
    assert "kubernetes: promoted public route for app" in contents


async def test_gke_import_creates_an_accounting_projection_without_an_agent_node(
    engine, service, settings, monkeypatch
):
    """GKE owns pod placement; imported releases must not require a Phase 2 VM."""
    _configure_kubernetes_import(engine, service)
    with Session(engine) as session:
        app = session.get(Service, service.id)
        assert app is not None
        app.build_config = {"compose_service": "app"}
        session.add(app)
        for node in session.exec(select(Node)).all():
            session.delete(node)
        session.commit()

    settings.runtime = "kubernetes"
    settings.kubernetes_target = "gke"
    settings.kubernetes_public_domain = "apps.rudder.example"
    settings.registry = "asia-south1-docker.pkg.dev/invytt-2483d/rudder"
    api = FakeKubernetesApi()

    async def use_gke_target(_settings):
        return api

    monkeypatch.setattr(deploy_service, "load_kubernetes_client", use_gke_target)

    with Session(engine) as session:
        deployment = Deployment(
            service_id=service.id,
            image_tag=(
                "asia-south1-docker.pkg.dev/invytt-2483d/rudder/app"
                "@sha256:" + "a" * 64
            ),
            commit_sha="abc123",
            status=DeploymentStatus.QUEUED,
        )
        session.add(deployment)
        session.commit()
        deployment_id = deployment.id

    outcome = await _run(engine, deployment_id, FakeAgent(), settings, _failing_builder)

    assert outcome.status is DeploymentStatus.LIVE
    with Session(engine) as session:
        node = session.exec(select(Node).where(Node.hostname == "gke-runtime")).one()
        assert node.reported_state == {"runtime": "kubernetes", "accounting_only": True}
        assert {
            instance.node_id
            for instance in session.exec(
                select(Instance).where(Instance.deployment_id == outcome.deployment_id)
            )
        } == {node.id}


async def test_imported_kubernetes_release_uses_its_persisted_public_domain(
    engine, service, settings, monkeypatch
):
    _configure_kubernetes_import(engine, service)
    with Session(engine) as session:
        app = session.get(Service, service.id)
        assert app is not None
        session.add(
            Domain(
                hostname="api.production.localhost",
                environment_id=app.environment_id,
                service_id=app.id,
                is_system=True,
            )
        )
        session.commit()

    settings.runtime = "kubernetes"
    api = FakeKubernetesApi()
    _use_kubernetes_api(monkeypatch, api)

    outcome = await _run(engine, _queue(engine, service.id), FakeAgent(), settings, _ok_builder)

    assert outcome.status is DeploymentStatus.LIVE
    assert api.public_routes["route-app"].host == "api.production.localhost"


async def test_imported_kubernetes_failure_keeps_previous_live_route_unchanged(
    engine, service, settings, monkeypatch
):
    """A failed candidate may be cleaned up, but cannot alter the live route."""
    _configure_kubernetes_import(engine, service)
    settings.runtime = "kubernetes"
    first_api = FakeKubernetesApi()
    failed_api = FakeKubernetesApi(fail_service="postgres")
    _use_kubernetes_api(monkeypatch, first_api, failed_api)

    first = await _run(engine, _queue(engine, service.id), FakeAgent(), settings, _ok_builder)
    previous_route = dict(first_api.public_routes)
    failed = await _run(engine, _queue(engine, service.id), FakeAgent(), settings, _ok_builder)

    assert first.status is DeploymentStatus.LIVE
    assert failed.status is DeploymentStatus.FAILED
    assert failed_api.public_routes == {}, "candidate must not promote a partial route"
    assert previous_route == first_api.public_routes
    assert any(name == "cleanup" for name, _ in failed_api.calls)
    with Session(engine) as session:
        prior = session.get(Deployment, first.deployment_id)
        assert prior is not None
        assert prior.status is DeploymentStatus.LIVE


async def test_imported_kubernetes_release_prunes_superseded_stateless_candidate(
    engine, service, settings, monkeypatch
):
    _configure_kubernetes_import(engine, service)
    settings.runtime = "kubernetes"
    first_api = FakeKubernetesApi()
    second_api = FakeKubernetesApi()
    _use_kubernetes_api(monkeypatch, first_api, second_api)

    first = await _run(engine, _queue(engine, service.id), FakeAgent(), settings, _ok_builder)
    second = await _run(engine, _queue(engine, service.id), FakeAgent(), settings, _ok_builder)

    assert first.status is DeploymentStatus.LIVE
    assert second.status is DeploymentStatus.LIVE
    assert ("cleanup", str(first.deployment_id)) in second_api.calls
    with Session(engine) as session:
        assert session.get(Deployment, first.deployment_id).status is DeploymentStatus.SUPERSEDED


async def test_imported_kubernetes_restore_reuses_the_recorded_image_without_a_builder(
    engine, service, settings, monkeypatch
):
    _configure_kubernetes_import(engine, service)
    settings.runtime = "kubernetes"
    api = FakeKubernetesApi()
    _use_kubernetes_api(monkeypatch, api)
    with Session(engine) as session:
        rollback = Deployment(
            service_id=service.id,
            image_tag="registry/acme/api@sha256:known-good",
            commit_sha="known-good",
            status=DeploymentStatus.QUEUED,
        )
        session.add(rollback)
        session.commit()
        rollback_id = rollback.id

    outcome = await _run(engine, rollback_id, FakeAgent(), settings, _failing_builder)

    assert outcome.status is DeploymentStatus.LIVE
    assert any(
        name == "workload" and value.startswith("app-") for name, value in api.calls
    )


async def test_imported_compose_start_failure_releases_its_node_reservation(
    engine, service, settings
):
    """A failed remote Compose start must not leave the node artificially full."""
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
                repository="acme/reservation-test",
                branch="main",
                compose_source="generated",
                compose_manifest="services:\n  app:\n    image: nginx:alpine\n",
                compose_project_name="rudder-reservation-test",
                project_id=environment.project_id,
                app_service_id=app.id,
            )
        )
        session.commit()

    outcome = await _run(
        engine, _queue(engine, service.id), FakeAgent(compose_fails=True), settings, _ok_builder
    )

    assert outcome.status is DeploymentStatus.FAILED
    with Session(engine) as session:
        node = session.exec(select(Node)).one()
        assert node.cpu_allocated == 0
        assert node.memory_allocated_mb == 0


async def test_imported_compose_redeployment_keeps_capacity_for_restore_targets(
    engine, service, settings
):
    """Both immutable Compose releases remain scheduled for instant restore."""
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
                repository="acme/capacity-test",
                branch="main",
                compose_source="generated",
                compose_manifest="services:\n  app:\n    build: .\n    expose: ['8080']\n",
                compose_project_name="rudder-capacity-test",
                project_id=environment.project_id,
                app_service_id=app.id,
            )
        )
        session.commit()

    first = await _run(engine, _queue(engine, service.id), FakeAgent(), settings, _ok_builder)
    second = await _run(engine, _queue(engine, service.id), FakeAgent(), settings, _ok_builder)
    assert first.status is DeploymentStatus.LIVE
    assert second.status is DeploymentStatus.LIVE

    with Session(engine) as session:
        node = session.exec(select(Node)).one()
        assert node.cpu_allocated == 2.0
        assert node.memory_allocated_mb == 1024


async def test_imported_compose_records_every_graph_container_after_release_is_live(
    engine, service, settings
):
    with Session(engine) as session:
        app = session.get(Service, service.id)
        assert app is not None
        environment = session.get(Environment, app.environment_id)
        assert environment is not None
        app.build_config = {"compose_service": "app", "managed_image": "nginx:alpine"}
        grafana = Service(
            environment_id=environment.id,
            name="grafana",
            container_port=3000,
            build_config={"compose_service": "grafana", "managed_by_service_id": str(app.id)},
        )
        session.add(grafana)
        session.add(app)
        session.commit()
        imported = GitHubImport(
            installation_id=7,
            repository="acme/observed-api",
            branch="main",
            compose_source="generated",
            compose_manifest=(
                "services:\n  app:\n    build: .\n    expose: ['8080']\n"
                "  grafana:\n    image: grafana/grafana\n    expose: ['3000']\n"
            ),
            compose_project_name="rudder-observed-test",
            project_id=environment.project_id,
            app_service_id=app.id,
        )
        session.add(imported)
        session.commit()
        session.add_all(
            [
                GitHubImportService(
                    github_import_id=imported.id,
                    service_id=app.id,
                    compose_service="app",
                    role="web",
                    is_public=True,
                ),
                GitHubImportService(
                    github_import_id=imported.id,
                    service_id=grafana.id,
                    compose_service="grafana",
                    role="observability",
                    is_public=True,
                ),
            ]
        )
        session.commit()

    outcome = await _run(
        engine,
        _queue(engine, service.id),
        FakeAgent(compose_services=("app", "grafana")),
        settings,
        _ok_builder,
    )

    assert outcome.status is DeploymentStatus.LIVE
    with Session(engine) as session:
        graph = list(session.exec(select(GitHubImportService)).all())
        assert all(entry.container_id for entry in graph)
        assert {
            entry.compose_service: (entry.container_id or "").rsplit("-", 1)[-1]
            for entry in graph
        } == {"app": "app", "grafana": "grafana"}
        instances = list(
            session.exec(
                select(Instance).where(Instance.deployment_id == outcome.deployment_id)
            ).all()
        )
        assert len(instances) == 2
        assert {instance.status for instance in instances} == {InstanceStatus.HEALTHY}


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


async def test_second_deploy_keeps_the_first_as_an_immutable_restore_target(
    engine, service, settings
):
    first = await _run(engine, _queue(engine, service.id), FakeAgent(), settings, _ok_builder)
    agent = FakeAgent()
    second = await _run(engine, _queue(engine, service.id), agent, settings, _ok_builder)

    assert second.status is DeploymentStatus.LIVE
    with Session(engine) as session:
        instances = {i.deployment_id: i for i in session.exec(select(Instance)).all()}
        assert instances[first.deployment_id].status is InstanceStatus.HEALTHY
        assert instances[first.deployment_id].stopped_at is None
        assert instances[second.deployment_id].status is InstanceStatus.HEALTHY
        # Exactly one Deployment is `live` afterwards.
        assert session.get(Deployment, first.deployment_id).status is DeploymentStatus.SUPERSEDED
    assert agent.removed == []


# ------------------------------------------------------------------ D14: concurrency


async def test_concurrent_deploys_produce_one_live_release_and_keep_restore_targets(
    engine, service, settings
):
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
        assert len(healthy) == 2, "both successful releases remain restore targets"
        assert {instance.deployment_id for instance in healthy} == {winner_id, loser_id}
        # The newer push wins in the end, and exactly one Deployment receives traffic.
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


async def test_interrupted_deploying_release_resumes_from_its_built_image(
    engine, service, settings
):
    """A control-plane restart must not strand a running candidate forever.

    The image has already been pushed when the interruption occurs. Recovery
    must reuse that immutable artifact, finish the normal health/traffic path,
    and never invoke the source builder a second time.
    """
    with Session(engine) as session:
        deployment = Deployment(
            service_id=service.id,
            image_tag="registry/api:already-built",
            status=DeploymentStatus.DEPLOYING,
        )
        session.add(deployment)
        session.commit()
        deployment_id = deployment.id

    async def should_not_build(*_args, **_kwargs):
        raise AssertionError("an interrupted release must reuse its built image")

    outcome = await _run(engine, deployment_id, FakeAgent(), settings, should_not_build)

    assert outcome.status is DeploymentStatus.LIVE
    with Session(engine) as session:
        assert session.get(Deployment, deployment_id).status is DeploymentStatus.LIVE


async def test_interrupted_compose_release_adopts_its_running_candidate(
    engine, service, settings
):
    """Recovery must not require a fresh scheduler heartbeat after compose up.

    A control-plane restart may occur in the gap between the agent starting a
    Compose project and the control plane recording its Instance rows.  The
    node may still look stale at that instant, but the project itself is the
    source of truth and must be adopted rather than failed for capacity.
    """
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
                repository="acme/recoverable-compose",
                branch="main",
                compose_source="generated",
                compose_manifest="services:\n  app:\n    build: .\n    expose: ['8080']\n",
                compose_project_name="rudder-recoverable-compose",
                project_id=environment.project_id,
                app_service_id=app.id,
            )
        )
        deployment = Deployment(
            service_id=app.id,
            image_tag="registry/app:already-built",
            status=DeploymentStatus.DEPLOYING,
        )
        session.add(deployment)
        session.commit()
        deployment_id = deployment.id

    agent = FakeAgent()

    async def should_not_build(*_args, **_kwargs):
        raise AssertionError("an interrupted Compose release must reuse its image")

    outcome = await _run(engine, deployment_id, agent, settings, should_not_build)

    assert outcome.status is DeploymentStatus.LIVE
    assert agent.compose_projects == [], "existing candidate must not be started twice"
    with Session(engine) as session:
        assert session.get(Deployment, deployment_id).status is DeploymentStatus.LIVE


async def test_worker_recovers_only_the_newest_interrupted_release(engine, service, settings):
    """A restart must not revive stale work behind the interrupted release."""
    from rudder_cp.logs.store import BuildLogStore
    from rudder_cp.services.worker import recover_interrupted_deployments

    with Session(engine) as session:
        stale = Deployment(
            service_id=service.id,
            status=DeploymentStatus.BUILDING,
            created_at=datetime.now(UTC) - timedelta(seconds=1),
        )
        current = Deployment(
            service_id=service.id,
            image_tag="registry/api:already-built",
            status=DeploymentStatus.DEPLOYING,
        )
        session.add_all([stale, current])
        session.commit()
        stale_id, current_id = stale.id, current.id

    recovered = await recover_interrupted_deployments(
        engine=engine,
        settings=settings,
        store=BuildLogStore(settings.build_log_dir),
        agent=FakeAgent(),  # type: ignore[arg-type]
    )

    assert recovered == 1
    with Session(engine) as session:
        assert session.get(Deployment, stale_id).status is DeploymentStatus.FAILED
        assert session.get(Deployment, current_id).status is DeploymentStatus.LIVE


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
