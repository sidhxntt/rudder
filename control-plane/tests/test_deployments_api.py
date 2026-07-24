"""Deployment endpoints and the GitHub webhook.

The webhook is the one endpoint on this service that an unauthenticated
stranger can reach, so most of what is asserted here is about refusing them.
"""

import hashlib
import hmac
import json
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from rudder_cp.config import Settings
from rudder_cp.db import get_session
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
from rudder_cp.routers import deployments as deployments_router
from rudder_cp.routers import webhooks as webhooks_router
from rudder_cp.schemas.common import install_error_handlers

SECRET = "hook-secret"


@pytest.fixture(name="engine")
def engine_fixture() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="seed")
def seed_fixture(engine: Engine) -> dict[str, str]:
    with Session(engine) as session:
        user = User(email="a@b.c", password_hash="x")
        session.add(user)
        session.commit()
        project = Project(name="shop", owner_id=user.id)
        session.add(project)
        session.commit()
        environment = Environment(project_id=project.id, name="production")
        node = Node(hostname="localhost", ip_address="127.0.0.1")
        session.add(environment)
        session.add(node)
        session.commit()
        with_repo = Service(
            environment_id=environment.id,
            name="api",
            source_repo="me/shop-api",
            source_branch="main",
        )
        without_repo = Service(environment_id=environment.id, name="db")
        session.add(with_repo)
        session.add(without_repo)
        session.commit()
        return {
            "service": str(with_repo.id),
            "no_repo": str(without_repo.id),
            "node": str(node.id),
        }


@pytest.fixture(name="client")
def client_fixture(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from rudder_cp import config
    from rudder_cp.routers import webhooks

    settings = Settings(secret_keys="", github_webhook_secret=SECRET)
    monkeypatch.setattr(config, "get_settings", lambda: settings)
    monkeypatch.setattr(webhooks, "get_settings", lambda: settings)
    monkeypatch.setattr(webhooks, "get_engine", lambda: engine)

    app = FastAPI()
    install_error_handlers(app)
    app.include_router(deployments_router.router)
    app.include_router(webhooks_router.router)

    def session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    with TestClient(app) as client:
        yield client


def _push(repo: str = "me/shop-api", branch: str = "main", sha: str = "a" * 40) -> bytes:
    return json.dumps(
        {"repository": {"full_name": repo}, "ref": f"refs/heads/{branch}", "after": sha}
    ).encode()


def _sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


# ------------------------------------------------------------------ deployments


def test_deploy_queues_and_returns_202(client: TestClient, seed: dict[str, str]) -> None:
    response = client.post(f"/services/{seed['service']}/deploy", json={})
    assert response.status_code == 202
    assert response.json()["status"] == "queued"


def test_deploy_accepts_an_explicit_sha(client: TestClient, seed: dict[str, str]) -> None:
    response = client.post(f"/services/{seed['service']}/deploy", json={"commit_sha": "b" * 40})
    assert response.json()["commit_sha"] == "b" * 40


def test_deploying_a_service_with_no_repo_is_a_readable_422(
    client: TestClient, seed: dict[str, str]
) -> None:
    response = client.post(f"/services/{seed['no_repo']}/deploy", json={})
    assert response.status_code == 422
    assert response.json()["code"] == "no_source_repo"


def test_deploying_a_compose_child_points_to_its_owning_release(
    client: TestClient, engine: Engine, seed: dict[str, str]
) -> None:
    with Session(engine) as session:
        child = session.get(Service, UUID(seed["no_repo"]))
        assert child is not None
        child.build_config = {"managed_by_service_id": seed["service"]}
        session.add(child)
        session.commit()

    response = client.post(f"/services/{seed['no_repo']}/deploy", json={})

    assert response.status_code == 422
    assert response.json()["code"] == "managed_by_compose"
    assert response.json()["details"]["release_service_id"] == seed["service"]


def test_deploying_an_unknown_service_is_404(client: TestClient) -> None:
    response = client.post(f"/services/{uuid4()}/deploy", json={})
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_fetching_an_unknown_deployment_is_404(client: TestClient) -> None:
    response = client.get(f"/deployments/{uuid4()}")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_deployments_are_listed_newest_first(client: TestClient, seed: dict[str, str]) -> None:
    first = client.post(f"/services/{seed['service']}/deploy", json={}).json()["id"]
    second = client.post(f"/services/{seed['service']}/deploy", json={}).json()["id"]
    listed = [d["id"] for d in client.get(f"/services/{seed['service']}/deployments").json()]
    assert listed[0] == second and first in listed


def test_a_compose_child_lists_its_owner_release_history(
    client: TestClient, engine: Engine, seed: dict[str, str]
) -> None:
    """Compose children inherit the owner release state and its build-log id."""
    owner_id = UUID(seed["service"])
    child_id = UUID(seed["no_repo"])
    with Session(engine) as session:
        owner = session.get(Service, owner_id)
        assert owner is not None
        environment = session.get(Environment, owner.environment_id)
        assert environment is not None
        child = session.get(Service, child_id)
        assert child is not None
        child.build_config = {"managed_by_service_id": str(owner_id)}
        record = GitHubImport(
            installation_id=42,
            repository="acme/shop",
            branch="main",
            compose_source="repository",
            compose_manifest="services: {}",
            compose_project_name="rudder-shop",
            project_id=environment.project_id,
            app_service_id=owner_id,
        )
        session.add(record)
        session.flush()
        session.add(
            GitHubImportService(
                github_import_id=record.id,
                service_id=child_id,
                compose_service="worker",
                role="worker",
                is_public=False,
            )
        )
        deployment = Deployment(service_id=owner_id, status=DeploymentStatus.BUILDING)
        session.add(deployment)
        session.commit()
        deployment_id = deployment.id

    response = client.get(f"/services/{child_id}/deployments")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": str(deployment_id),
            "service_id": str(owner_id),
            "status": "building",
            "image_tag": None,
            "commit_sha": None,
            "error_message": None,
            "created_at": response.json()[0]["created_at"],
            "became_live_at": None,
        }
    ]


def test_instances_are_exposed_for_a_service(
    client: TestClient, engine: Engine, seed: dict[str, str]
) -> None:
    """The canvas cannot tell live from dead without this."""
    deployment_id = client.post(f"/services/{seed['service']}/deploy", json={}).json()["id"]
    with Session(engine) as session:
        session.add(
            Instance(
                deployment_id=UUID(deployment_id),
                node_id=UUID(seed["node"]),
                container_id="abc123",
                status=InstanceStatus.HEALTHY,
            )
        )
        session.commit()

    instances = client.get(f"/services/{seed['service']}/instances").json()
    assert [i["status"] for i in instances] == ["healthy"]
    assert instances[0]["container_id"] == "abc123"


# ------------------------------------------------------------------ webhook


def test_a_valid_push_queues_a_deployment(
    client: TestClient, engine: Engine, seed: dict[str, str]
) -> None:
    body = _push()
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-Hub-Signature-256": _sign(body), "X-GitHub-Event": "push"},
    )
    assert response.status_code == 202
    assert len(response.json()["queued"]) == 1
    with Session(engine) as session:
        deployment = session.exec(select(Deployment)).one()
        assert deployment.commit_sha == "a" * 40
        assert deployment.status is DeploymentStatus.QUEUED


def test_an_unsigned_push_is_refused(client: TestClient, engine: Engine) -> None:
    body = _push()
    response = client.post(
        "/webhooks/github", content=body, headers={"X-GitHub-Event": "push"}
    )
    assert response.status_code == 401
    with Session(engine) as session:
        assert session.exec(select(Deployment)).all() == []


def test_a_wrongly_signed_push_is_refused(client: TestClient, engine: Engine) -> None:
    body = _push()
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-Hub-Signature-256": _sign(body, "wrong-secret"), "X-GitHub-Event": "push"},
    )
    assert response.status_code == 401
    with Session(engine) as session:
        assert session.exec(select(Deployment)).all() == []


def test_a_tampered_body_is_refused(client: TestClient) -> None:
    """The signature covers the body, so changing the SHA must invalidate it."""
    signature = _sign(_push())
    tampered = _push(sha="f" * 40)
    response = client.post(
        "/webhooks/github",
        content=tampered,
        headers={"X-Hub-Signature-256": signature, "X-GitHub-Event": "push"},
    )
    assert response.status_code == 401


def test_a_push_to_another_branch_queues_nothing(client: TestClient) -> None:
    body = _push(branch="feature/x")
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-Hub-Signature-256": _sign(body), "X-GitHub-Event": "push"},
    )
    assert response.json()["queued"] == []


def test_a_push_to_an_unknown_repo_queues_nothing(client: TestClient) -> None:
    body = _push(repo="someone/else")
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-Hub-Signature-256": _sign(body), "X-GitHub-Event": "push"},
    )
    assert response.json()["queued"] == []


def test_a_deleted_branch_builds_nothing(client: TestClient) -> None:
    """GitHub reports an all-zero SHA when a branch is deleted."""
    body = _push(sha="0" * 40)
    response = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-Hub-Signature-256": _sign(body), "X-GitHub-Event": "push"},
    )
    assert response.json() == {"queued": [], "detail": "branch deleted"}


def test_ping_is_answered_and_other_events_ignored(client: TestClient) -> None:
    body = _push()
    ping = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-Hub-Signature-256": _sign(body), "X-GitHub-Event": "ping"},
    )
    assert ping.json()["detail"] == "pong"

    other = client.post(
        "/webhooks/github",
        content=body,
        headers={"X-Hub-Signature-256": _sign(body), "X-GitHub-Event": "issues"},
    )
    assert other.json()["queued"] == []


def test_an_unconfigured_secret_refuses_rather_than_trusting_the_caller(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from rudder_cp.routers import webhooks

    monkeypatch.setattr(webhooks, "get_settings", lambda: Settings(secret_keys=""))
    monkeypatch.setattr(webhooks, "get_engine", lambda: engine)
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(webhooks.router)
    with TestClient(app) as client:
        response = client.post(
            "/webhooks/github", content=_push(), headers={"X-GitHub-Event": "push"}
        )
    assert response.status_code == 503
    assert response.json()["code"] == "webhook_not_configured"
