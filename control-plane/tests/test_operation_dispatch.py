"""Manual-operation dispatch never creates another source build.

These tests exercise the durable bridge from an Operations API intent to an
existing immutable deployment.  The deploy worker is allowed to apply the
image again to reconcile Kubernetes, but it must never invoke BuildKit merely
because a user changed replicas, resources, or a schedule.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

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
    OperationKind,
    OperationStatus,
    Project,
    Service,
    ServiceOperation,
    ServiceOperationsState,
    User,
)
from rudder_cp.services import operation_dispatch, rollbacks


@pytest.fixture
def engine(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path/'operations.db'}")
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


def _imported_app(session: Session) -> tuple[Service, Node]:
    user = User(email="operations@example.test", password_hash="x")
    session.add(user)
    session.commit()
    project = Project(name="operations", owner_id=user.id)
    environment = Environment(project_id=project.id, name="production")
    node = Node(hostname="operations-node", ip_address="127.0.0.1")
    session.add_all((project, environment, node))
    session.commit()
    app = Service(
        environment_id=environment.id,
        name="app",
        source_repo="owner/app",
        source_branch="main",
        container_port=8080,
    )
    session.add(app)
    session.commit()
    imported = GitHubImport(
        installation_id=1,
        repository="owner/app",
        branch="main",
        compose_source="generated",
        compose_manifest="services: {}\n",
        compose_project_name="operations-test",
        project_id=project.id,
        app_service_id=app.id,
    )
    session.add(imported)
    session.commit()
    session.add(
        GitHubImportService(
            github_import_id=imported.id,
            service_id=app.id,
            compose_service="app",
            role="app",
            is_public=True,
        )
    )
    session.add(
        Domain(
            hostname="app.production.localhost",
            environment_id=environment.id,
            service_id=app.id,
            is_system=True,
        )
    )
    session.commit()
    return app, node


def test_pending_scale_queues_the_current_immutable_image_without_a_build(engine) -> None:
    with Session(engine) as session:
        app, _node = _imported_app(session)
        live = Deployment(
            service_id=app.id,
            status=DeploymentStatus.LIVE,
            image_tag="registry.local/app:immutable-sha",
            commit_sha="a" * 40,
        )
        session.add(live)
        session.commit()
        state = ServiceOperationsState(
            service_id=app.id,
            desired={"replicas": 3},
            version=1,
            pending_reconciliation=True,
        )
        operation = ServiceOperation(
            service_id=app.id,
            kind=OperationKind.SCALE,
            status=OperationStatus.PENDING,
            requested={"replicas": 3},
        )
        session.add_all((state, operation))
        session.commit()

        queued = operation_dispatch.queue_pending_operation_reconciliations(session)
        assert len(queued) == 1
        candidate = session.get(Deployment, queued[0])
        assert candidate is not None
        assert candidate.status is DeploymentStatus.QUEUED
        assert candidate.image_tag == "registry.local/app:immutable-sha"
        assert candidate.commit_sha == "a" * 40
        # It is a release row only; no source build metadata is invented.
        assert len(session.exec(select(Deployment)).all()) == 2


@pytest.mark.asyncio
async def test_pending_rollback_repoints_a_healthy_immutable_release_without_building(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    with Session(engine) as session:
        app, node = _imported_app(session)
        source = Deployment(
            service_id=app.id,
            status=DeploymentStatus.SUPERSEDED,
            image_tag="registry.local/app:old",
        )
        current = Deployment(
            service_id=app.id,
            status=DeploymentStatus.LIVE,
            image_tag="registry.local/app:new",
        )
        session.add_all((source, current))
        session.commit()
        session.add(
            Instance(
                deployment_id=source.id,
                node_id=node.id,
                container_id="old-healthy",
                status=InstanceStatus.HEALTHY,
            )
        )
        session.add(
            ServiceOperationsState(
                service_id=app.id,
                desired={},
                version=1,
                pending_reconciliation=True,
            )
        )
        session.add(
            ServiceOperation(
                service_id=app.id,
                kind=OperationKind.ROLLBACK,
                status=OperationStatus.PENDING,
                requested={"deployment_id": str(source.id)},
            )
        )
        session.commit()

        render = AsyncMock()
        monkeypatch.setattr("rudder_cp.services.rollbacks.traefik.render_all", render)
        assert await operation_dispatch.reconcile_pending_rollbacks(
            session, settings=Settings(secret_keys="")
        ) == 1
        session.refresh(source)
        session.refresh(current)
        operation = session.exec(select(ServiceOperation)).one()
        assert source.status is DeploymentStatus.LIVE
        assert current.status is DeploymentStatus.SUPERSEDED
        assert operation.status is OperationStatus.HEALTHY
        assert operation.observed["mechanism"] == "immutable_route_restore"
        assert len(session.exec(select(Deployment)).all()) == 2
        render.assert_awaited_once()


@pytest.mark.asyncio
async def test_kubernetes_rollback_repoints_only_the_stable_ingress(
    engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Kubernetes rollback must switch the existing route without rebuilding."""
    with Session(engine) as session:
        app, node = _imported_app(session)
        source = Deployment(
            service_id=app.id,
            status=DeploymentStatus.SUPERSEDED,
            image_tag="registry.local/app:old",
        )
        current = Deployment(
            service_id=app.id,
            status=DeploymentStatus.LIVE,
            image_tag="registry.local/app:new",
        )
        session.add_all((source, current))
        session.commit()
        session.add(
            Instance(
                deployment_id=source.id,
                node_id=node.id,
                container_id="old-healthy",
                status=InstanceStatus.HEALTHY,
            )
        )
        session.commit()

        class FakeKubernetesApi:
            def __init__(self) -> None:
                self.routes = []
                self.closed = False

            async def promote_public_service(self, namespace, spec) -> None:
                self.routes.append((namespace, spec))

            async def close(self) -> None:
                self.closed = True

        api = FakeKubernetesApi()

        async def from_kubeconfig(*_args, **_kwargs):
            return api

        render = AsyncMock()
        monkeypatch.setattr(
            "rudder_cp.services.rollbacks.AsyncKubernetesApi.from_kubeconfig",
            from_kubeconfig,
        )
        monkeypatch.setattr("rudder_cp.services.rollbacks.traefik.render_all", render)

        restored = await rollbacks.restore_immutable_deployment(
            session,
            deployment_id=source.id,
            settings=Settings(runtime="kubernetes", secret_keys=""),
        )

        assert restored.id == source.id
        assert source.status is DeploymentStatus.LIVE
        assert current.status is DeploymentStatus.SUPERSEDED
        assert api.closed is True
        assert len(api.routes) == 1
        namespace, route = api.routes[0]
        assert namespace.startswith("rudder-")
        assert route.host == "app.production.localhost"
        assert route.name == "route-app"
        assert route.backend_service_name == f"app-{str(source.id)[:8]}"
        assert route.backend_port == 8080
        render.assert_not_awaited()
