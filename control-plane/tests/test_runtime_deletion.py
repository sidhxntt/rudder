"""Runtime cleanup when a service or environment is deleted."""

import asyncio
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select

from rudder_cp.config import Settings, get_settings
from rudder_cp.db import get_session
from rudder_cp.models import (
    Deployment,
    DeploymentStatus,
    Domain,
    DomainTargetType,
    Environment,
    GitHubImport,
    GitHubImportService,
    Instance,
    InstanceStatus,
    Node,
    Project,
    Service,
    ServiceManagedCapabilities,
    ServiceOperation,
    User,
    Volume,
)
from rudder_cp.models.operations import OperationKind
from rudder_cp.routers import services as services_router
from rudder_cp.schemas.common import install_error_handlers
from rudder_cp.security import issue_token
from rudder_cp.services import environments, projects, services, traefik
from rudder_cp.services.agent_client import AgentError
from rudder_cp.services.services import RuntimeCleanupError


class RecordingAgent:
    def __init__(self) -> None:
        self.removed: list[str] = []

    async def remove(self, container_id: str, *, drain_seconds: float) -> None:
        assert drain_seconds == 0
        self.removed.append(container_id)


class FailingAgent:
    async def remove(self, container_id: str, *, drain_seconds: float) -> None:
        raise AgentError(f"cannot remove {container_id}")


class FailOnSecondRemovalAgent:
    def __init__(self) -> None:
        self.removed: list[str] = []

    async def remove(self, container_id: str, *, drain_seconds: float) -> None:
        if self.removed:
            raise AgentError(f"cannot remove {container_id}")
        self.removed.append(container_id)


def _route_files(settings: Settings) -> list[Path]:
    return list(Path(settings.traefik_dynamic_dir).glob("*.yml"))


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(traefik_dynamic_dir=str(tmp_path / "dynamic"))


def _live_service(session: Session, environment: Environment, node: Node, name: str) -> Service:
    service = Service(environment_id=environment.id, name=name, container_port=3000)
    session.add(service)
    session.flush()
    domain = Domain(
        hostname=f"{name}.{environment.name}.localhost",
        environment_id=environment.id,
        target_type=DomainTargetType.SERVICE,
        service_id=service.id,
        is_system=True,
    )
    deployment = Deployment(service_id=service.id, status=DeploymentStatus.LIVE)
    session.add(domain)
    session.add(deployment)
    session.flush()
    session.add(
        Instance(
            deployment_id=deployment.id,
            node_id=node.id,
            container_id=f"container-{name}",
            status=InstanceStatus.HEALTHY,
        )
    )
    session.commit()
    session.refresh(service)
    return service


async def test_deleting_a_live_service_removes_only_its_container_and_route(engine, settings):
    with Session(engine) as session:
        user = User(email="owner@example.com", password_hash="x")
        session.add(user)
        session.commit()
        project = Project(name="shop", owner_id=user.id)
        environment = Environment(project_id=project.id, name="production", is_production=True)
        node = Node(hostname="localhost", ip_address="127.0.0.1")
        session.add(project)
        session.add(environment)
        session.add(node)
        session.commit()
        api = _live_service(session, environment, node, "api")
        other = _live_service(session, environment, node, "other")

        await traefik.render_all(session, settings)
        route_files = await asyncio.to_thread(_route_files, settings)
        assert len(route_files) == 2

        agent = RecordingAgent()
        await services.delete_service(session, api.id, agent=agent, settings=settings)

        assert agent.removed == ["container-api"]
        assert session.get(Service, api.id) is None
        assert session.get(Service, other.id) is not None
        assert session.exec(select(Instance)).one().container_id == "container-other"
        assert len(await asyncio.to_thread(_route_files, settings)) == 1


async def test_deleting_a_service_removes_its_volume_before_the_service(engine, settings):
    """A managed add-on must be deletable even though its volume has an FK."""
    with Session(engine) as session:
        user = User(email="owner@example.com", password_hash="x")
        project = Project(name="shop", owner_id=user.id)
        environment = Environment(project_id=project.id, name="production", is_production=True)
        node = Node(hostname="localhost", ip_address="127.0.0.1")
        session.add(user)
        session.add(project)
        session.add(environment)
        session.add(node)
        session.commit()
        postgres = _live_service(session, environment, node, "postgres")
        volume = Volume(service_id=postgres.id, mount_path="/var/lib/postgresql/data")
        session.add(volume)
        session.commit()

        await services.delete_service(
            session, postgres.id, agent=RecordingAgent(), settings=settings
        )

        assert session.get(Service, postgres.id) is None
        assert session.get(Volume, volume.id) is None


async def test_deleting_a_service_removes_operation_history_before_the_service(
    engine, settings
):
    """Operation history has a service FK and must not block regular deletion."""
    with Session(engine) as session:
        user = User(email="owner@example.com", password_hash="x")
        project = Project(name="shop", owner_id=user.id)
        environment = Environment(project_id=project.id, name="production", is_production=True)
        node = Node(hostname="localhost", ip_address="127.0.0.1")
        session.add(user)
        session.add(project)
        session.add(environment)
        session.add(node)
        session.commit()
        api = _live_service(session, environment, node, "api")
        operation = ServiceOperation(
            service_id=api.id,
            kind=OperationKind.SCALE,
            requested={"replicas": 2},
        )
        session.add(operation)
        session.commit()

        await services.delete_service(session, api.id, agent=RecordingAgent(), settings=settings)

        assert session.get(Service, api.id) is None
        assert session.get(ServiceOperation, operation.id) is None


async def test_deleting_a_service_removes_managed_capabilities_before_the_service(
    engine, settings
):
    """Trusted capability metadata has a service FK and must not block teardown."""
    with Session(engine) as session:
        user = User(email="owner@example.com", password_hash="x")
        project = Project(name="shop", owner_id=user.id)
        environment = Environment(project_id=project.id, name="production", is_production=True)
        node = Node(hostname="localhost", ip_address="127.0.0.1")
        session.add(user)
        session.add(project)
        session.add(environment)
        session.add(node)
        session.commit()
        postgres = _live_service(session, environment, node, "postgres")
        capabilities = ServiceManagedCapabilities(
            service_id=postgres.id,
            database_engine="postgres",
            allowed_job_commands=[["pg_dump"]],
        )
        session.add(capabilities)
        session.commit()

        await services.delete_service(
            session, postgres.id, agent=RecordingAgent(), settings=settings
        )

        assert session.get(Service, postgres.id) is None
        assert session.get(ServiceManagedCapabilities, capabilities.id) is None


async def test_deleting_a_live_environment_removes_its_containers_and_routes(engine, settings):
    with Session(engine) as session:
        user = User(email="owner@example.com", password_hash="x")
        session.add(user)
        session.commit()
        project = Project(name="shop", owner_id=user.id)
        production = Environment(project_id=project.id, name="production", is_production=True)
        staging = Environment(project_id=project.id, name="staging")
        node = Node(hostname="localhost", ip_address="127.0.0.1")
        session.add(project)
        session.add(production)
        session.add(staging)
        session.add(node)
        session.commit()
        api = _live_service(session, production, node, "api")
        staging_api = _live_service(session, staging, node, "staging-api")
        capabilities = ServiceManagedCapabilities(
            service_id=api.id,
            database_engine="postgres",
            allowed_job_commands=[["pg_dump"]],
        )
        session.add(capabilities)
        session.commit()

        await traefik.render_all(session, settings)
        agent = RecordingAgent()
        await environments.delete_environment(
            session, production.id, agent=agent, settings=settings
        )

        assert agent.removed == ["container-api"]
        assert session.get(Environment, production.id) is None
        assert session.get(Service, api.id) is None
        assert session.get(ServiceManagedCapabilities, capabilities.id) is None
        assert session.get(Service, staging_api.id) is not None
        assert len(await asyncio.to_thread(_route_files, settings)) == 1


async def test_failed_service_runtime_cleanup_keeps_database_and_route(engine, settings):
    with Session(engine) as session:
        user = User(email="owner@example.com", password_hash="x")
        project = Project(name="shop", owner_id=user.id)
        environment = Environment(project_id=project.id, name="production", is_production=True)
        node = Node(hostname="localhost", ip_address="127.0.0.1")
        session.add(user)
        session.add(project)
        session.add(environment)
        session.add(node)
        session.commit()
        api = _live_service(session, environment, node, "api")
        await traefik.render_all(session, settings)

        with pytest.raises(RuntimeCleanupError, match="cannot remove container-api"):
            await services.delete_service(session, api.id, agent=FailingAgent(), settings=settings)

        assert session.get(Service, api.id) is not None
        assert session.exec(select(Deployment)).one().service_id == api.id
        assert session.exec(select(Instance)).one().container_id == "container-api"
        assert session.exec(select(Domain)).one().service_id == api.id
        assert len(await asyncio.to_thread(_route_files, settings)) == 1


async def test_partial_runtime_cleanup_removes_dead_backend_from_traefik(engine, settings):
    with Session(engine) as session:
        user = User(email="owner@example.com", password_hash="x")
        project = Project(name="shop", owner_id=user.id)
        environment = Environment(project_id=project.id, name="production", is_production=True)
        node = Node(hostname="localhost", ip_address="127.0.0.1")
        session.add(user)
        session.add(project)
        session.add(environment)
        session.add(node)
        session.commit()
        api = _live_service(session, environment, node, "api")
        deployment = session.exec(select(Deployment)).one()
        first_instance = session.exec(select(Instance)).one()
        first_instance.container_id = "container-first"
        session.add(first_instance)
        session.add(
            Instance(
                deployment_id=deployment.id,
                node_id=node.id,
                container_id="container-second",
                status=InstanceStatus.HEALTHY,
            )
        )
        session.commit()
        await traefik.render_all(session, settings)

        agent = FailOnSecondRemovalAgent()
        with pytest.raises(RuntimeCleanupError, match="cannot remove container-second"):
            await services.delete_service(session, api.id, agent=agent, settings=settings)

        assert agent.removed == ["container-first"]
        assert session.get(Service, api.id) is not None
        assert session.exec(select(Deployment)).one().service_id == api.id
        instances = session.exec(select(Instance).order_by(Instance.created_at)).all()
        assert [instance.status for instance in instances] == [
            InstanceStatus.STOPPED,
            InstanceStatus.HEALTHY,
        ]
        route = (await asyncio.to_thread(_route_files, settings))[0].read_text()
        assert "container-fi" not in route
        assert "container-se" in route


async def test_failed_environment_runtime_cleanup_keeps_database_and_route(engine, settings):
    with Session(engine) as session:
        user = User(email="owner@example.com", password_hash="x")
        project = Project(name="shop", owner_id=user.id)
        environment = Environment(project_id=project.id, name="production", is_production=True)
        node = Node(hostname="localhost", ip_address="127.0.0.1")
        session.add(user)
        session.add(project)
        session.add(environment)
        session.add(node)
        session.commit()
        api = _live_service(session, environment, node, "api")
        await traefik.render_all(session, settings)

        with pytest.raises(RuntimeCleanupError, match="cannot remove container-api"):
            await environments.delete_environment(
                session, environment.id, agent=FailingAgent(), settings=settings
            )

        assert session.get(Environment, environment.id) is not None
        assert session.get(Service, api.id) is not None
        assert session.exec(select(Deployment)).one().service_id == api.id
        assert session.exec(select(Instance)).one().container_id == "container-api"
        assert session.exec(select(Domain)).one().service_id == api.id
        assert len(await asyncio.to_thread(_route_files, settings)) == 1


async def test_deleting_a_live_project_removes_its_containers_and_routes(engine, settings):
    with Session(engine) as session:
        user = User(email="owner@example.com", password_hash="x")
        project = Project(name="shop", owner_id=user.id)
        other_project = Project(name="other", owner_id=user.id)
        environment = Environment(project_id=project.id, name="production", is_production=True)
        other_environment = Environment(
            project_id=other_project.id, name="production", is_production=True
        )
        node = Node(hostname="localhost", ip_address="127.0.0.1")
        session.add(user)
        session.add(project)
        session.add(other_project)
        session.add(environment)
        session.add(other_environment)
        session.add(node)
        session.commit()
        api = _live_service(session, environment, node, "api")
        other_api = _live_service(session, other_environment, node, "other-api")
        capabilities = ServiceManagedCapabilities(
            service_id=api.id,
            database_engine="postgres",
            allowed_job_commands=[["pg_dump"]],
        )
        session.add(capabilities)
        session.commit()
        await traefik.render_all(session, settings)

        agent = RecordingAgent()
        await projects.delete_project(session, project.id, agent=agent, settings=settings)

        assert agent.removed == ["container-api"]
        assert session.get(Project, project.id) is None
        assert session.get(Service, api.id) is None
        assert session.get(ServiceManagedCapabilities, capabilities.id) is None
        assert session.get(Service, other_api.id) is not None
        assert len(await asyncio.to_thread(_route_files, settings)) == 1


async def test_deleting_imported_project_removes_import_metadata(engine, settings):
    """An import must not leave foreign-key rows behind after project deletion."""
    with Session(engine) as session:
        user = User(email="owner@example.com", password_hash="x")
        project = Project(name="imported", owner_id=user.id)
        environment = Environment(project_id=project.id, name="production", is_production=True)
        node = Node(hostname="localhost", ip_address="127.0.0.1")
        session.add(user)
        session.add(project)
        session.add(environment)
        session.add(node)
        session.commit()

        app = _live_service(session, environment, node, "app")
        imported = GitHubImport(
            installation_id=1,
            repository="acme/imported",
            branch="main",
            compose_source="generated",
            compose_manifest="services: {}\n",
            compose_project_name="rudder-imported",
            project_id=project.id,
            app_service_id=app.id,
        )
        session.add(imported)
        session.flush()
        session.add(
            GitHubImportService(
                github_import_id=imported.id,
                service_id=app.id,
                compose_service="app",
                role="web",
                is_public=True,
            )
        )
        session.commit()

        await projects.delete_project(
            session, project.id, agent=RecordingAgent(), settings=settings
        )

        assert session.get(Project, project.id) is None
        assert session.get(GitHubImport, imported.id) is None
        assert session.exec(select(GitHubImportService)).all() == []


async def test_failed_project_runtime_cleanup_keeps_database_and_route(engine, settings):
    with Session(engine) as session:
        user = User(email="owner@example.com", password_hash="x")
        project = Project(name="shop", owner_id=user.id)
        environment = Environment(project_id=project.id, name="production", is_production=True)
        node = Node(hostname="localhost", ip_address="127.0.0.1")
        session.add(user)
        session.add(project)
        session.add(environment)
        session.add(node)
        session.commit()
        api = _live_service(session, environment, node, "api")
        await traefik.render_all(session, settings)

        with pytest.raises(RuntimeCleanupError, match="cannot remove container-api"):
            await projects.delete_project(
                session, project.id, agent=FailingAgent(), settings=settings
            )

        assert session.get(Project, project.id) is not None
        assert session.get(Environment, environment.id) is not None
        assert session.get(Service, api.id) is not None
        assert session.exec(select(Deployment)).one().service_id == api.id
        assert session.exec(select(Instance)).one().container_id == "container-api"
        assert session.exec(select(Domain)).one().service_id == api.id
        assert len(await asyncio.to_thread(_route_files, settings)) == 1


def test_service_delete_returns_runtime_cleanup_error(engine, settings, monkeypatch):
    monkeypatch.setenv("RUDDER_JWT_SECRET", "runtime-deletion-api-test-secret-32")
    get_settings.cache_clear()
    with Session(engine) as session:
        user = User(email="owner@example.com", password_hash="x")
        project = Project(name="shop", owner_id=user.id)
        environment = Environment(project_id=project.id, name="production", is_production=True)
        node = Node(hostname="localhost", ip_address="127.0.0.1")
        session.add(user)
        session.add(project)
        session.add(environment)
        session.add(node)
        session.commit()
        api = _live_service(session, environment, node, "api")
        token = issue_token(user.id).token

    app = FastAPI()
    app.state.settings = settings
    app.state.agent = FailingAgent()
    install_error_handlers(app)
    app.include_router(services_router.router)

    def override_get_session():
        with Session(engine) as request_session:
            yield request_session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
        response = client.delete(f"/services/{api.id}")

    assert response.status_code == 503
    assert response.json()["code"] == "runtime_cleanup_failed"
    with Session(engine) as session:
        assert session.get(Service, api.id) is not None
    get_settings.cache_clear()
