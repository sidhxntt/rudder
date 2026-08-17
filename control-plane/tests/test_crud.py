"""CRUD API tests: projects, environments, services, domains.

The app under test is built here rather than imported from ``main.py`` — this
workstream owns four routers and nothing else, and the test should fail when
one of them breaks, not when someone else's lifespan does.

Storage is SQLite in memory. That is enough for everything asserted here:
uniqueness, the Domain CHECK constraint, and cascade behaviour are all
enforced by SQLite too.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from rudder_cp.config import get_settings
from rudder_cp.db import get_session
from rudder_cp.models import (
    Deployment,
    Domain,
    Environment,
    Project,
    Service,
    User,
    Variable,
    Volume,
)
from rudder_cp.routers import domains as domains_router
from rudder_cp.routers import environments as environments_router
from rudder_cp.routers import projects as projects_router
from rudder_cp.routers import services as services_router
from rudder_cp.schemas.common import install_error_handlers
from rudder_cp.security import issue_token
from rudder_cp.services.naming import NAME_PATTERN

BASE_DOMAIN = get_settings().base_domain
TLS_ON = get_settings().tls_mode == "acme"


@pytest.fixture(name="engine")
def engine_fixture() -> Iterator[Engine]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(email="owner@example.com", password_hash="not-a-real-hash"))
        session.commit()
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="client")
def client_fixture(
    engine: Engine, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[TestClient]:
    monkeypatch.setenv("RUDDER_JWT_SECRET", "crud-service-owner-test-secret-32")
    get_settings.cache_clear()
    app = FastAPI()
    app.state.settings = get_settings().model_copy(
        update={"traefik_dynamic_dir": str(tmp_path / "dynamic")}
    )
    app.state.agent = object()
    install_error_handlers(app)
    app.include_router(projects_router.router)
    app.include_router(environments_router.router)
    app.include_router(services_router.router)
    app.include_router(domains_router.router)

    def override_get_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    with Session(engine) as session:
        owner = session.exec(select(User).where(User.email == "owner@example.com")).one()
        token = issue_token(owner.id).token
    try:
        with TestClient(app, headers={"Authorization": f"Bearer {token}"}) as client:
            yield client
    finally:
        get_settings.cache_clear()


# --------------------------------------------------------------------------
# Helpers.
# --------------------------------------------------------------------------


def make_project(client: TestClient, name: str = "shop") -> dict[str, Any]:
    response = client.post("/projects", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def production_environment(client: TestClient, project_id: str) -> dict[str, Any]:
    response = client.get(f"/projects/{project_id}/environments")
    assert response.status_code == 200, response.text
    environments = response.json()
    return next(env for env in environments if env["name"] == "production")


def make_service(
    client: TestClient, environment_id: str, name: str = "api", **extra: Any
) -> dict[str, Any]:
    response = client.post(
        f"/environments/{environment_id}/services",
        json={"name": name, **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.fixture(name="env_id")
def env_id_fixture(client: TestClient) -> str:
    project = make_project(client)
    return production_environment(client, project["id"])["id"]


# --------------------------------------------------------------------------
# Projects.
# --------------------------------------------------------------------------


def test_project_lifecycle(client: TestClient) -> None:
    created = make_project(client, "shop")
    assert created["name"] == "shop"
    assert set(created) == {"id", "name", "owner_id", "created_at"}

    project_id = created["id"]

    listed = client.get("/projects")
    assert listed.status_code == 200
    assert [p["id"] for p in listed.json()] == [project_id]

    fetched = client.get(f"/projects/{project_id}")
    assert fetched.status_code == 200
    assert fetched.json() == created

    patched = client.patch(f"/projects/{project_id}", json={"name": "shop-2"})
    assert patched.status_code == 200
    assert patched.json()["name"] == "shop-2"
    # Every mutation returns the full resource.
    assert set(patched.json()) == set(created)

    replaced = client.put(f"/projects/{project_id}", json={"name": "shop-3"})
    assert replaced.status_code == 200
    assert replaced.json()["name"] == "shop-3"

    deleted = client.delete(f"/projects/{project_id}")
    assert deleted.status_code == 204
    assert client.get(f"/projects/{project_id}").status_code == 404


def test_project_create_makes_a_production_environment(client: TestClient) -> None:
    project = make_project(client)
    environments = client.get(f"/projects/{project['id']}/environments").json()
    assert [env["name"] for env in environments] == ["production"]
    assert environments[0]["is_production"] is True


def test_unknown_project_returns_uniform_error(client: TestClient) -> None:
    response = client.get(f"/projects/{uuid4()}")
    assert response.status_code == 404
    body = response.json()
    assert set(body) == {"code", "message", "details"}
    assert body["code"] == "not_found"


def test_service_routes_hide_other_owners_services(client: TestClient, engine: Engine) -> None:
    """A valid session for one project owner cannot mutate another owner's service."""
    with Session(engine) as session:
        intruder = User(email="other-owner@example.com", password_hash="not-a-real-hash")
        session.add(intruder)
        session.commit()
        foreign_project = Project(name="other-project", owner_id=intruder.id)
        session.add(foreign_project)
        session.commit()
        foreign_environment = Environment(
            project_id=foreign_project.id,
            name="production",
            is_production=True,
        )
        session.add(foreign_environment)
        session.commit()
        foreign_service = Service(environment_id=foreign_environment.id, name="private-api")
        session.add(foreign_service)
        session.commit()
        foreign_service_id = foreign_service.id

    response = client.patch(f"/services/{foreign_service_id}", json={"name": "taken-over"})
    assert response.status_code == 404, response.text
    assert client.get(f"/services/{foreign_service_id}").status_code == 404


@pytest.mark.parametrize("template", ["postgres", "redis", "mysql"])
def test_database_template_is_private_durable_and_idempotent(
    client: TestClient, engine: Engine, env_id: str, template: str
) -> None:
    response = client.post(f"/environments/{env_id}/database-templates/{template}")
    assert response.status_code == 201, response.text
    database = response.json()
    assert database["name"] == template
    assert database["kind"] == "database"

    # Catalog databases deliberately have no publicly routed system Domain.
    assert client.get(f"/services/{database['id']}/domains").json() == []
    with Session(engine) as session:
        variables = session.exec(
            select(Variable).where(Variable.service_id == UUID(database["id"]))
        ).all()
        volumes = session.exec(
            select(Volume).where(Volume.service_id == UUID(database["id"]))
        ).all()
        secret_values = [variable.value_encrypted for variable in variables]
    assert volumes
    assert secret_values

    repeated = client.post(f"/environments/{env_id}/database-templates/{template}")
    assert repeated.status_code == 201, repeated.text
    assert repeated.json()["id"] == database["id"]
    with Session(engine) as session:
        after_repeat = session.exec(
            select(Variable).where(Variable.service_id == UUID(database["id"]))
        ).all()
    assert [variable.value_encrypted for variable in after_repeat] == secret_values


def test_volume_backed_service_delete_requires_confirmation(
    client: TestClient, engine: Engine, env_id: str
) -> None:
    database = client.post(f"/environments/{env_id}/database-templates/postgres").json()
    refused = client.delete(f"/services/{database['id']}")
    assert refused.status_code == 409, refused.text
    assert "persistent volume" in refused.json()["message"]

    deleted = client.delete(f"/services/{database['id']}?confirm_volume_deletion=true")
    assert deleted.status_code == 204, deleted.text
    with Session(engine) as session:
        assert session.exec(
            select(Volume).where(Volume.service_id == UUID(database["id"]))
        ).first() is None


# --------------------------------------------------------------------------
# Environments.
# --------------------------------------------------------------------------


def test_environment_lifecycle(client: TestClient) -> None:
    project = make_project(client)
    created = client.post(
        f"/projects/{project['id']}/environments", json={"name": "staging"}
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "staging"
    assert body["project_id"] == project["id"]
    assert body["is_production"] is False
    assert body["github_pr_number"] is None
    assert set(body) == {
        "id",
        "project_id",
        "name",
        "is_production",
        "github_pr_number",
        "created_at",
    }

    env_id = body["id"]
    assert client.get(f"/environments/{env_id}").json() == body

    patched = client.patch(f"/environments/{env_id}", json={"is_production": True})
    assert patched.status_code == 200
    assert patched.json()["is_production"] is True
    assert patched.json()["name"] == "staging"

    replaced = client.put(f"/environments/{env_id}", json={"name": "staging"})
    assert replaced.status_code == 200
    # PUT resets omitted fields to their defaults.
    assert replaced.json()["is_production"] is False

    assert client.delete(f"/environments/{env_id}").status_code == 204
    assert client.get(f"/environments/{env_id}").status_code == 404


def test_clone_copies_declarative_graph_but_no_runtime_history(
    client: TestClient, engine: Engine
) -> None:
    project = make_project(client)
    production = production_environment(client, project["id"])
    api = make_service(
        client,
        production["id"],
        "api",
        source_repo="acme/api",
        source_branch="main",
        canvas_x=144,
        canvas_y=288,
    )
    database = make_service(client, production["id"], "postgres", kind="database")
    with Session(engine) as session:
        session.add(
            Variable(
                service_id=UUID(api["id"]),
                key="DATABASE_URL",
                value_encrypted=b"ciphertext-is-copied-not-decrypted",
                is_reference=True,
            )
        )
        session.add(
            Volume(service_id=UUID(database["id"]), mount_path="/var/lib/postgresql/data", size_mb=2048)
        )
        session.add(Deployment(service_id=UUID(api["id"])))
        session.commit()

    cloned = client.post(
        f"/environments/{production['id']}/clone",
        json={"name": "staging"},
    )
    assert cloned.status_code == 201, cloned.text
    staging = cloned.json()
    assert staging["name"] == "staging"
    assert staging["is_production"] is False

    services = client.get(f"/environments/{staging['id']}/services").json()
    assert [(service["name"], service["canvas_x"], service["canvas_y"]) for service in services] == [
        ("api", 144.0, 288.0),
        ("postgres", 0.0, 0.0),
    ]
    assert services[0]["source_branch"] == "main"
    assert {domain["hostname"] for domain in client.get(f"/environments/{staging['id']}/domains").json()} == {
        "api.staging.localhost",
        "postgres.staging.localhost",
    }
    with Session(engine) as session:
        cloned_api = session.exec(select(Service).where(Service.environment_id == UUID(staging["id"]), Service.name == "api")).one()
        cloned_postgres = session.exec(select(Service).where(Service.environment_id == UUID(staging["id"]), Service.name == "postgres")).one()
        assert session.exec(select(Variable).where(Variable.service_id == cloned_api.id)).one().value_encrypted.startswith(b"ciphertext")
        volume = session.exec(select(Volume).where(Volume.service_id == cloned_postgres.id)).one()
        assert volume.size_mb == 2048
        assert volume.node_id is None
        assert session.exec(select(Deployment).where(Deployment.service_id == cloned_api.id)).all() == []


def test_clone_is_atomic_when_target_name_is_taken(client: TestClient, engine: Engine) -> None:
    project = make_project(client)
    production = production_environment(client, project["id"])
    make_service(client, production["id"], "api")
    assert client.post(f"/projects/{project['id']}/environments", json={"name": "staging"}).status_code == 201
    response = client.post(f"/environments/{production['id']}/clone", json={"name": "staging"})
    assert response.status_code == 409
    with Session(engine) as session:
        assert session.exec(select(Service).where(Service.environment_id != UUID(production["id"]))).all() == []


def test_environment_creation_does_not_expose_or_allocate_a_legacy_mesh_subnet(
    client: TestClient,
) -> None:
    """Kubernetes namespaces, not WireGuard CIDRs, isolate environments."""

    project = make_project(client)
    response = client.post(
        f"/projects/{project['id']}/environments", json={"name": "staging"}
    )

    assert response.status_code == 201, response.text
    assert "wg_subnet" not in response.json()


def test_duplicate_environment_name_is_409(client: TestClient) -> None:
    project = make_project(client)
    response = client.post(
        f"/projects/{project['id']}/environments", json={"name": "production"}
    )
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["code"] == "environment_name_taken"
    assert body["details"]["name"] == "production"


def test_same_environment_name_in_two_projects_is_fine(client: TestClient) -> None:
    first = make_project(client, "shop")
    second = make_project(client, "blog")
    for project in (first, second):
        response = client.post(
            f"/projects/{project['id']}/environments", json={"name": "staging"}
        )
        assert response.status_code == 201, response.text


def test_environment_under_unknown_project_is_404(client: TestClient) -> None:
    response = client.post(f"/projects/{uuid4()}/environments", json={"name": "staging"})
    assert response.status_code == 404


# --------------------------------------------------------------------------
# D9 name validation.
# --------------------------------------------------------------------------


BAD_NAMES = ["Bad_Name", "-leading-hyphen", "a" * 40, "", "trailing-", "UPPER", "has space"]


@pytest.mark.parametrize("name", BAD_NAMES)
def test_environment_name_validation(client: TestClient, name: str) -> None:
    project = make_project(client)
    response = client.post(f"/projects/{project['id']}/environments", json={"name": name})
    assert response.status_code == 422, response.text
    body = response.json()
    assert set(body) == {"code", "message", "details"}
    assert body["code"] == "validation_error"


@pytest.mark.parametrize("name", BAD_NAMES)
def test_service_name_validation(client: TestClient, env_id: str, name: str) -> None:
    response = client.post(f"/environments/{env_id}/services", json={"name": name})
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "validation_error"


@pytest.mark.parametrize("name", ["a", "api", "api-2", "a" * 32, "0", "a-b-c"])
def test_good_service_names_are_accepted(client: TestClient, env_id: str, name: str) -> None:
    response = client.post(f"/environments/{env_id}/services", json={"name": name})
    assert response.status_code == 201, response.text


def test_rename_to_a_bad_name_is_422(client: TestClient, env_id: str) -> None:
    service = make_service(client, env_id)
    response = client.patch(f"/services/{service['id']}", json={"name": "Bad_Name"})
    assert response.status_code == 422
    assert client.get(f"/services/{service['id']}").json()["name"] == "api"


def test_name_pattern_is_the_one_from_d9() -> None:
    assert NAME_PATTERN == r"^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$"


# --------------------------------------------------------------------------
# Services.
# --------------------------------------------------------------------------


SERVICE_FIELDS = {
    "id",
    "environment_id",
    "name",
    "kind",
    "source_repo",
    "source_branch",
    "dockerfile_path",
    "build_config",
    "start_command",
    "container_port",
    "health_check_path",
    "health_check_port",
    "cpu_limit",
    "memory_limit_mb",
    "replica_count",
    "canvas_x",
    "canvas_y",
    "created_at",
}


def test_service_lifecycle(client: TestClient, env_id: str) -> None:
    created = make_service(client, env_id, source_repo="me/shop-api", container_port=3000)
    assert set(created) == SERVICE_FIELDS
    assert created["kind"] == "app"
    assert created["source_repo"] == "me/shop-api"
    assert created["container_port"] == 3000
    assert created["source_branch"] == "main"

    service_id = created["id"]
    assert client.get(f"/services/{service_id}").json() == created

    listed = client.get(f"/environments/{env_id}/services")
    assert [s["id"] for s in listed.json()] == [service_id]

    patched = client.patch(f"/services/{service_id}", json={"replica_count": 3})
    assert patched.status_code == 200
    assert set(patched.json()) == SERVICE_FIELDS
    assert patched.json()["replica_count"] == 3
    assert patched.json()["container_port"] == 3000

    assert client.delete(f"/services/{service_id}").status_code == 204
    assert client.get(f"/services/{service_id}").status_code == 404


def test_duplicate_service_name_is_409(client: TestClient, env_id: str) -> None:
    make_service(client, env_id, "api")
    response = client.post(f"/environments/{env_id}/services", json={"name": "api"})
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "service_name_taken"


def test_same_service_name_in_two_environments_is_fine(client: TestClient) -> None:
    project = make_project(client)
    production = production_environment(client, project["id"])
    staging = client.post(
        f"/projects/{project['id']}/environments", json={"name": "staging"}
    ).json()
    make_service(client, production["id"], "api")
    make_service(client, staging["id"], "api")


def test_service_put_is_idempotent(client: TestClient, env_id: str) -> None:
    service = make_service(client, env_id, source_repo="me/shop-api", canvas_x=10.0)
    body = {
        "name": "api",
        "kind": "app",
        "source_repo": "me/other",
        "source_branch": "trunk",
        "container_port": 9000,
        "cpu_limit": 2.0,
        "memory_limit_mb": 1024,
        "replica_count": 2,
        "canvas_x": 5.0,
        "canvas_y": 6.0,
    }
    first = client.put(f"/services/{service['id']}", json=body)
    second = client.put(f"/services/{service['id']}", json=body)
    assert first.status_code == 200, first.text
    assert second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["source_repo"] == "me/other"
    assert first.json()["container_port"] == 9000


def test_service_put_resets_omitted_fields(client: TestClient, env_id: str) -> None:
    service = make_service(client, env_id, container_port=3000, replica_count=4)
    replaced = client.put(f"/services/{service['id']}", json={"name": "api"})
    assert replaced.status_code == 200
    assert replaced.json()["container_port"] == 8080
    assert replaced.json()["replica_count"] == 1


def test_canvas_position_is_writable_and_inert(client: TestClient, env_id: str) -> None:
    """D6 — canvas_x/y are UI metadata. They persist, and nothing else moves."""
    service = make_service(client, env_id)
    before = client.get(f"/services/{service['id']}").json()
    domains_before = client.get(f"/services/{service['id']}/domains").json()

    moved = client.patch(f"/services/{service['id']}", json={"canvas_x": 12.5, "canvas_y": -3.0})
    assert moved.status_code == 200
    body = moved.json()
    assert (body["canvas_x"], body["canvas_y"]) == (12.5, -3.0)

    unchanged = {k: v for k, v in body.items() if k not in {"canvas_x", "canvas_y"}}
    assert unchanged == {k: v for k, v in before.items() if k not in {"canvas_x", "canvas_y"}}
    assert client.get(f"/services/{service['id']}/domains").json() == domains_before


def test_service_under_unknown_environment_is_404(client: TestClient) -> None:
    response = client.post(f"/environments/{uuid4()}/services", json={"name": "api"})
    assert response.status_code == 404


# --------------------------------------------------------------------------
# D15 system domains.
# --------------------------------------------------------------------------


def test_service_create_makes_a_system_domain(client: TestClient, env_id: str) -> None:
    service = make_service(client, env_id, "api")
    domains = client.get(f"/services/{service['id']}/domains").json()
    assert len(domains) == 1
    domain = domains[0]
    assert domain["hostname"] == f"api.production.{BASE_DOMAIN}"
    assert domain["target_type"] == "service"
    assert domain["service_id"] == service["id"]
    assert domain["deployment_id"] is None
    assert domain["is_system"] is True
    assert domain["tls_enabled"] is TLS_ON


def test_renaming_a_service_moves_its_system_domain(client: TestClient, env_id: str) -> None:
    service = make_service(client, env_id, "api")
    renamed = client.patch(f"/services/{service['id']}", json={"name": "gateway"})
    assert renamed.status_code == 200
    domains = client.get(f"/services/{service['id']}/domains").json()
    assert [d["hostname"] for d in domains] == [f"gateway.production.{BASE_DOMAIN}"]


def test_renaming_an_environment_moves_every_system_domain(client: TestClient) -> None:
    project = make_project(client)
    env = production_environment(client, project["id"])
    make_service(client, env["id"], "api")
    make_service(client, env["id"], "web")

    renamed = client.patch(f"/environments/{env['id']}", json={"name": "prod"})
    assert renamed.status_code == 200, renamed.text

    hostnames = {d["hostname"] for d in client.get(f"/environments/{env['id']}/domains").json()}
    assert hostnames == {f"api.prod.{BASE_DOMAIN}", f"web.prod.{BASE_DOMAIN}"}


def test_system_domain_cannot_be_deleted(client: TestClient, env_id: str) -> None:
    service = make_service(client, env_id, "api")
    domain = client.get(f"/services/{service['id']}/domains").json()[0]
    response = client.delete(f"/domains/{domain['id']}")
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "system_domain_immutable"
    assert client.get(f"/domains/{domain['id']}").status_code == 200


def test_system_domain_cannot_be_mutated(client: TestClient, env_id: str) -> None:
    service = make_service(client, env_id, "api")
    domain = client.get(f"/services/{service['id']}/domains").json()[0]

    patched = client.patch(f"/domains/{domain['id']}", json={"hostname": "hijack.example.com"})
    assert patched.status_code == 403
    assert patched.json()["code"] == "system_domain_immutable"

    replaced = client.put(
        f"/domains/{domain['id']}",
        json={
            "hostname": "hijack.example.com",
            "target_type": "service",
            "service_id": service["id"],
        },
    )
    assert replaced.status_code == 403


def test_system_domain_cannot_be_forged(client: TestClient, env_id: str) -> None:
    """is_system is not a request field, so a POST cannot claim it."""
    service = make_service(client, env_id, "api")
    response = client.post(
        f"/environments/{env_id}/domains",
        json={
            "hostname": "shop.example.com",
            "target_type": "service",
            "service_id": service["id"],
            "is_system": True,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["is_system"] is False


def test_service_delete_takes_its_system_domain(
    client: TestClient, engine: Engine, env_id: str
) -> None:
    service = make_service(client, env_id, "api")
    assert client.delete(f"/services/{service['id']}").status_code == 204
    with Session(engine) as session:
        assert session.exec(select(Domain)).all() == []


def test_creating_a_service_whose_system_hostname_is_taken_is_409(
    client: TestClient, engine: Engine, env_id: str
) -> None:
    existing = make_service(client, env_id, "web")
    squat = client.post(
        f"/environments/{env_id}/domains",
        json={
            "hostname": f"api.production.{BASE_DOMAIN}",
            "target_type": "service",
            "service_id": existing["id"],
        },
    )
    assert squat.status_code == 201, squat.text

    response = client.post(f"/environments/{env_id}/services", json={"name": "api"})
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "hostname_taken"

    # The failed create must not have half-landed.
    assert [s["name"] for s in client.get(f"/environments/{env_id}/services").json()] == ["web"]
    with Session(engine) as session:
        assert session.exec(select(Service).where(Service.name == "api")).first() is None


# --------------------------------------------------------------------------
# Domains.
# --------------------------------------------------------------------------


DOMAIN_FIELDS = {
    "id",
    "hostname",
    "environment_id",
    "target_type",
    "service_id",
    "deployment_id",
    "is_system",
    "tls_enabled",
    "created_at",
}


def test_domain_lifecycle(client: TestClient, env_id: str) -> None:
    service = make_service(client, env_id, "api")
    created = client.post(
        f"/environments/{env_id}/domains",
        json={
            "hostname": "Shop.Example.COM",
            "target_type": "service",
            "service_id": service["id"],
            "tls_enabled": True,
        },
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert set(body) == DOMAIN_FIELDS
    # Hostnames are normalised so uniqueness is a plain string comparison.
    assert body["hostname"] == "shop.example.com"
    assert body["is_system"] is False
    assert body["tls_enabled"] is True

    domain_id = body["id"]
    assert client.get(f"/domains/{domain_id}").json() == body

    listed = client.get(f"/environments/{env_id}/domains").json()
    assert {d["hostname"] for d in listed} == {
        "shop.example.com",
        f"api.production.{BASE_DOMAIN}",
    }

    patched = client.patch(f"/domains/{domain_id}", json={"tls_enabled": False})
    assert patched.status_code == 200
    assert set(patched.json()) == DOMAIN_FIELDS
    assert patched.json()["tls_enabled"] is False

    assert client.delete(f"/domains/{domain_id}").status_code == 204
    assert client.get(f"/domains/{domain_id}").status_code == 404


def test_domain_put_is_idempotent(client: TestClient, env_id: str) -> None:
    service = make_service(client, env_id, "api")
    created = client.post(
        f"/environments/{env_id}/domains",
        json={"hostname": "shop.example.com", "service_id": service["id"]},
    ).json()
    body = {
        "hostname": "shop.example.com",
        "target_type": "service",
        "service_id": service["id"],
        "tls_enabled": True,
    }
    first = client.put(f"/domains/{created['id']}", json=body)
    second = client.put(f"/domains/{created['id']}", json=body)
    assert first.status_code == 200, first.text
    assert first.json() == second.json()
    assert first.json()["tls_enabled"] is True


def test_duplicate_hostname_is_409(client: TestClient, env_id: str) -> None:
    service = make_service(client, env_id, "api")
    payload = {"hostname": "shop.example.com", "service_id": service["id"]}
    assert client.post(f"/environments/{env_id}/domains", json=payload).status_code == 201
    clash = client.post(f"/environments/{env_id}/domains", json=payload)
    assert clash.status_code == 409, clash.text
    assert clash.json()["code"] == "hostname_taken"


def test_hostname_colliding_with_a_system_domain_is_409(client: TestClient, env_id: str) -> None:
    service = make_service(client, env_id, "api")
    clash = client.post(
        f"/environments/{env_id}/domains",
        json={
            "hostname": f"api.production.{BASE_DOMAIN}",
            "service_id": service["id"],
        },
    )
    assert clash.status_code == 409, clash.text
    assert clash.json()["code"] == "hostname_taken"
    assert clash.json()["details"]["is_system"] is True


def test_domain_with_both_targets_is_422(client: TestClient, env_id: str) -> None:
    response = client.post(
        f"/environments/{env_id}/domains",
        json={
            "hostname": "shop.example.com",
            "target_type": "service",
            "service_id": str(uuid4()),
            "deployment_id": str(uuid4()),
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "validation_error"


def test_domain_with_no_target_is_422(client: TestClient, env_id: str) -> None:
    response = client.post(
        f"/environments/{env_id}/domains",
        json={"hostname": "shop.example.com", "target_type": "service"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "validation_error"


def test_domain_target_type_must_match_the_id(client: TestClient, env_id: str) -> None:
    service = make_service(client, env_id, "api")
    response = client.post(
        f"/environments/{env_id}/domains",
        json={
            "hostname": "shop.example.com",
            "target_type": "deployment",
            "service_id": service["id"],
        },
    )
    assert response.status_code == 422, response.text


def test_patching_a_domain_into_two_targets_is_422(
    client: TestClient, engine: Engine, env_id: str
) -> None:
    """The CHECK constraint stays a constraint; the API answers before it fires."""
    service = make_service(client, env_id, "api")
    created = client.post(
        f"/environments/{env_id}/domains",
        json={"hostname": "shop.example.com", "service_id": service["id"]},
    ).json()

    with Session(engine) as session:
        deployment = Deployment(service_id=UUID(service["id"]), image_tag="api:abc123")
        session.add(deployment)
        session.commit()
        deployment_id = str(deployment.id)

    response = client.patch(
        f"/domains/{created['id']}", json={"deployment_id": deployment_id}
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "invalid_request"
    assert client.get(f"/domains/{created['id']}").json()["deployment_id"] is None


def test_domain_can_be_retargeted_to_a_deployment(
    client: TestClient, engine: Engine, env_id: str
) -> None:
    service = make_service(client, env_id, "api")
    created = client.post(
        f"/environments/{env_id}/domains",
        json={"hostname": "shop.example.com", "service_id": service["id"]},
    ).json()

    with Session(engine) as session:
        deployment = Deployment(service_id=UUID(service["id"]), image_tag="api:abc123")
        session.add(deployment)
        session.commit()
        deployment_id = str(deployment.id)

    response = client.patch(
        f"/domains/{created['id']}",
        json={
            "target_type": "deployment",
            "service_id": None,
            "deployment_id": deployment_id,
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["target_type"] == "deployment"
    assert response.json()["deployment_id"] == deployment_id
    assert response.json()["service_id"] is None


def test_domain_cannot_target_another_environment(client: TestClient) -> None:
    project = make_project(client)
    production = production_environment(client, project["id"])
    staging = client.post(
        f"/projects/{project['id']}/environments", json={"name": "staging"}
    ).json()
    service = make_service(client, production["id"], "api")

    response = client.post(
        f"/environments/{staging['id']}/domains",
        json={"hostname": "shop.example.com", "service_id": service["id"]},
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "invalid_request"


def test_domain_targeting_an_unknown_service_is_404(client: TestClient, env_id: str) -> None:
    response = client.post(
        f"/environments/{env_id}/domains",
        json={"hostname": "shop.example.com", "service_id": str(uuid4())},
    )
    assert response.status_code == 404, response.text


# --------------------------------------------------------------------------
# Cascade deletes. No orphans.
# --------------------------------------------------------------------------


def _row_counts(engine: Engine) -> dict[str, int]:
    with Session(engine) as session:
        return {
            "environment": len(session.exec(select(Environment)).all()),
            "service": len(session.exec(select(Service)).all()),
            "domain": len(session.exec(select(Domain)).all()),
            "variable": len(session.exec(select(Variable)).all()),
            "deployment": len(session.exec(select(Deployment)).all()),
        }


def _populate(client: TestClient, engine: Engine) -> dict[str, Any]:
    project = make_project(client)
    production = production_environment(client, project["id"])
    staging = client.post(
        f"/projects/{project['id']}/environments", json={"name": "staging"}
    ).json()
    api = make_service(client, production["id"], "api")
    make_service(client, staging["id"], "api")
    client.post(
        f"/environments/{production['id']}/domains",
        json={"hostname": "shop.example.com", "service_id": api["id"]},
    )
    with Session(engine) as session:
        session.add(Deployment(service_id=UUID(api["id"]), image_tag="api:abc123"))
        session.add(
            Variable(service_id=UUID(api["id"]), key="PORT", value_encrypted=b"ciphertext")
        )
        session.commit()
    return {"project": project, "production": production, "staging": staging, "api": api}


def test_deleting_a_service_leaves_no_orphans(client: TestClient, engine: Engine) -> None:
    fixture = _populate(client, engine)
    assert client.delete(f"/services/{fixture['api']['id']}").status_code == 204
    counts = _row_counts(engine)
    assert counts == {
        "environment": 2,
        "service": 1,
        "domain": 1,  # only staging's system domain remains
        "variable": 0,
        "deployment": 0,
    }


def test_deleting_an_environment_leaves_no_orphans(client: TestClient, engine: Engine) -> None:
    fixture = _populate(client, engine)
    assert client.delete(f"/environments/{fixture['production']['id']}").status_code == 204
    counts = _row_counts(engine)
    assert counts == {
        "environment": 1,
        "service": 1,
        "domain": 1,
        "variable": 0,
        "deployment": 0,
    }


def test_deleting_a_project_leaves_no_orphans(client: TestClient, engine: Engine) -> None:
    fixture = _populate(client, engine)
    assert client.delete(f"/projects/{fixture['project']['id']}").status_code == 204
    assert _row_counts(engine) == {
        "environment": 0,
        "service": 0,
        "domain": 0,
        "variable": 0,
        "deployment": 0,
    }
    assert client.get("/projects").json() == []


def test_deleting_something_twice_is_404(client: TestClient, env_id: str) -> None:
    service = make_service(client, env_id)
    assert client.delete(f"/services/{service['id']}").status_code == 204
    assert client.delete(f"/services/{service['id']}").status_code == 404


# --------------------------------------------------------------------------
# OpenAPI. The Python SDK and the TS client are generated from this schema.
# --------------------------------------------------------------------------


def test_openapi_is_sdk_grade(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    operation_ids: list[str] = []

    for path, item in spec["paths"].items():
        for method, operation in item.items():
            where = f"{method.upper()} {path}"
            operation_ids.append(operation["operationId"])
            assert operation.get("summary"), f"{where} has no summary"

            success = [code for code in operation["responses"] if code.startswith("2")]
            assert len(success) == 1, where
            body = operation["responses"][success[0]]
            if success[0] != "204":
                assert "application/json" in body["content"], where

            for code, response in operation["responses"].items():
                if code.startswith("2"):
                    continue
                schema = response["content"]["application/json"]["schema"]
                # Errors are uniform, and the schema says so.
                assert schema["$ref"].endswith("/ErrorEnvelope"), f"{where} {code}"

    assert len(operation_ids) == len(set(operation_ids))
    assert "ErrorEnvelope" in spec["components"]["schemas"]
