"""Protected, idempotent API tests for persisted service operations."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from rudder_cp.config import get_settings
from rudder_cp.db import get_session
from rudder_cp.models import Environment, Project, Service, ServiceKind, User
from rudder_cp.routers import auth as auth_router
from rudder_cp.routers import operations as operations_router
from rudder_cp.schemas.common import install_error_handlers
from rudder_cp.security import issue_token


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
        user = User(email="owner@example.com", password_hash="x")
        intruder = User(email="intruder@example.com", password_hash="x")
        session.add_all((user, intruder))
        session.commit()
        project = Project(name="operations", owner_id=user.id)
        session.add(project)
        session.commit()
        environment = Environment(project_id=project.id, name="production")
        session.add(environment)
        session.commit()
        app = Service(environment_id=environment.id, name="api", kind=ServiceKind.APP)
        primary = Service(
            environment_id=environment.id,
            name="postgres",
            kind=ServiceKind.DATABASE,
            build_config={"data_role": "primary"},
        )
        replica = Service(
            environment_id=environment.id,
            name="postgres-replica",
            kind=ServiceKind.DATABASE,
            build_config={"data_role": "read_replica"},
        )
        session.add_all((app, primary, replica))
        session.commit()
        return {
            "token": issue_token(user.id).token,
            "intruder_token": issue_token(intruder.id).token,
            "app": str(app.id),
            "primary": str(primary.id),
            "replica": str(replica.id),
        }


@pytest.fixture(name="client")
def client_fixture(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("RUDDER_JWT_SECRET", "operations-api-test-secret")
    get_settings.cache_clear()

    app = FastAPI()
    install_error_handlers(app)
    app.include_router(
        operations_router.router,
        dependencies=[Depends(auth_router.get_current_user)],
    )

    def session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        get_settings.cache_clear()


def headers(seed: dict[str, str], key: str = "request-1") -> dict[str, str]:
    return {
        "Authorization": f"Bearer {seed['token']}",
        "Idempotency-Key": key,
    }


def create_scale(
    client: TestClient,
    seed: dict[str, str],
    *,
    service: str | None = None,
    replicas: int = 2,
    key: str = "request-1",
    **extra: Any,
) -> dict[str, Any]:
    response = client.post(
        f"/services/{service or seed['app']}/operations/scale",
        headers=headers(seed, key),
        json={"replicas": replicas, **extra},
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_operations_are_protected_and_require_idempotency_key(
    client: TestClient, seed: dict[str, str]
) -> None:
    assert client.get(f"/services/{seed['app']}/operations").status_code == 401

    response = client.post(
        f"/services/{seed['app']}/operations/scale",
        headers={"Authorization": f"Bearer {seed['token']}"},
        json={"replicas": 2},
    )
    assert response.status_code == 422


def test_scale_is_idempotent_and_ignores_client_service_identity(
    client: TestClient, seed: dict[str, str]
) -> None:
    first = create_scale(
        client,
        seed,
        service=seed["replica"],
        service_kind="app",
        data_role="primary",
    )
    second = create_scale(
        client,
        seed,
        service=seed["replica"],
        service_kind="database",
        data_role="read_replica",
    )

    assert first["id"] == second["id"]
    assert first["kind"] == "scale"
    assert first["status"] == "pending"
    assert first["requested"] == {"replicas": 2}
    assert "service_kind" not in first["requested"]
    assert "data_role" not in first["requested"]


def test_primary_database_scale_cannot_be_spoofed_by_client_hints(
    client: TestClient, seed: dict[str, str]
) -> None:
    response = client.post(
        f"/services/{seed['primary']}/operations/scale",
        headers=headers(seed),
        json={"replicas": 2, "service_kind": "app", "data_role": "read_replica"},
    )
    assert response.status_code == 422
    assert "database primaries" in response.json()["message"]


def test_same_idempotency_key_with_different_payload_does_not_collide(
    client: TestClient, seed: dict[str, str]
) -> None:
    create_scale(client, seed, replicas=2, key="same-client-key")
    second = client.post(
        f"/services/{seed['app']}/operations/scale",
        headers=headers(seed, "same-client-key"),
        json={"replicas": 3},
    )

    assert second.status_code == 409
    assert second.json()["code"] == "conflict"


def test_operations_hide_other_users_services(
    client: TestClient, seed: dict[str, str]
) -> None:
    response = client.get(
        f"/services/{seed['app']}/operations",
        headers={"Authorization": f"Bearer {seed['intruder_token']}"},
    )
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


def test_patch_operations_persists_declared_desired_intent(
    client: TestClient, seed: dict[str, str]
) -> None:
    response = client.patch(
        f"/services/{seed['app']}/operations",
        headers={"Authorization": f"Bearer {seed['token']}"},
        json={"autoscaling": {"min_replicas": 2, "max_replicas": 4}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["autoscaling"] == {
        "min_replicas": 2,
        "max_replicas": 4,
        "target_cpu_percent": 80,
        "target_memory_percent": None,
    }


def test_canonical_operation_families_create_typed_records(
    client: TestClient, seed: dict[str, str]
) -> None:
    cases = (
        ("app", "/operations/rollout", {"strategy": "blue_green"}),
        ("app", "/operations/rollback", {"deployment_id": "00000000-0000-0000-0000-000000000001"}),
        ("app", "/operations/placement", {"topology_spread": True}),
        ("primary", "/operations/data/backups", {"retention_days": 14}),
        (
            "primary",
            "/operations/data/restore",
            {"backup_id": "00000000-0000-0000-0000-000000000002", "acknowledge_data_loss": True},
        ),
        ("primary", "/operations/data/read-replicas", {"replicas": 1}),
        (
            "primary",
            "/operations/data/storage",
            {"current_size_mb": 1024, "requested_size_mb": 2048},
        ),
        ("app", "/operations/jobs/run", {"command": ["python", "manage.py", "migrate"]}),
        ("app", "/operations/observability", {"prometheus": True, "grafana": True}),
    )
    for index, (service, path, payload) in enumerate(cases):
        response = client.post(
            f"/services/{seed[service]}{path}",
            headers=headers(seed, f"canonical-{index}"),
            json=payload,
        )
        assert response.status_code == 202, response.text


def test_schedule_can_be_created_and_deleted(
    client: TestClient, seed: dict[str, str]
) -> None:
    created = client.post(
        f"/services/{seed['app']}/operations/schedules",
        headers=headers(seed, "schedule-create"),
        json={"cron": "0 * * * *", "command": ["python", "cleanup.py"]},
    )
    assert created.status_code == 202, created.text

    deleted = client.delete(
        f"/services/{seed['app']}/operations/schedules/{created.json()['id']}",
        headers={"Authorization": f"Bearer {seed['token']}"},
    )
    assert deleted.status_code == 204, deleted.text


def test_operations_are_registered_on_the_real_application() -> None:
    from rudder_cp.main import create_app

    app = create_app()
    response = TestClient(app).get("/services/00000000-0000-0000-0000-000000000000/operations")
    assert response.status_code == 401


def test_operation_idempotency_migration_enforces_one_key_per_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'operations-idempotency.db'}"
    monkeypatch.setenv("RUDDER_DATABASE_URL", database_url)
    get_settings.cache_clear()
    control_plane = Path(__file__).parents[1]
    config = Config(str(control_plane / "alembic.ini"))
    config.set_main_option("script_location", str(control_plane / "migrations"))
    try:
        # ``c1d24...`` only adds a PostgreSQL enum member; SQLite has no
        # equivalent ALTER TYPE. Stamp its otherwise identical SQLite schema
        # so this test can exercise the later operations migrations.
        command.upgrade(config, "b9a11d39f9d1")
        command.stamp(config, "c1d24ef9a8b7")
        command.upgrade(config, "0008")
        command.upgrade(config, "0009")
        engine = sa.create_engine(database_url)
        with engine.connect() as connection:
            constraints = sa.inspect(connection).get_unique_constraints("service_operation")
        assert any(
            constraint["name"] == "uq_service_operation_service_idempotency_key"
            for constraint in constraints
        )
        engine.dispose()
    finally:
        get_settings.cache_clear()


def test_list_is_newest_first_and_data_operations_are_type_checked(
    client: TestClient, seed: dict[str, str]
) -> None:
    scale = create_scale(client, seed, key="scale-history")
    backup = client.post(
        f"/services/{seed['app']}/operations/backups",
        headers=headers(seed, "backup-history"),
        json={"retention_days": 14},
    )
    assert backup.status_code == 422

    resource = client.post(
        f"/services/{seed['app']}/operations/resources",
        headers=headers(seed, "resource-history"),
        json={"cpu_request": "250m", "memory_limit_mb": 512},
    )
    assert resource.status_code == 202, resource.text

    listed = client.get(
        f"/services/{seed['app']}/operations",
        headers={"Authorization": f"Bearer {seed['token']}"},
    )
    assert listed.status_code == 200
    assert [operation["id"] for operation in listed.json()] == [resource.json()["id"], scale["id"]]


def test_operations_return_uniform_not_found_and_validation_errors(
    client: TestClient, seed: dict[str, str]
) -> None:
    missing = client.get(
        "/services/00000000-0000-0000-0000-000000000000/operations",
        headers={"Authorization": f"Bearer {seed['token']}"},
    )
    assert missing.status_code == 404
    assert missing.json()["code"] == "not_found"

    invalid = client.post(
        f"/services/{seed['app']}/operations/autoscaling",
        headers=headers(seed, "invalid-autoscale"),
        json={"min_replicas": 5, "max_replicas": 2},
    )
    assert invalid.status_code == 422
    assert invalid.json()["code"] in {"validation_error", "invalid_request"}
