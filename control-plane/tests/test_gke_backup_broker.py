"""Tests for the narrow GKE Workload Identity backup broker."""

from __future__ import annotations

import json

import httpx
import pytest
from fastapi.testclient import TestClient

from rudder_cp.backup_broker import create_backup_identity_broker_app
from rudder_cp.runtime.backup_identity import (
    GkeBackupIdentityBroker,
    HttpBackupIdentityBroker,
    MetadataGoogleIamPolicyApi,
)


class FakeGoogleIam:
    def __init__(self, policy: dict[str, object]) -> None:
        self.policy = policy
        self.updated: list[tuple[str, dict[str, object]]] = []

    async def get_policy(self, service_account: str) -> dict[str, object]:
        assert service_account == "rudder-backup@example.iam.gserviceaccount.com"
        return self.policy

    async def set_policy(self, service_account: str, policy: dict[str, object]) -> None:
        self.updated.append((service_account, policy))


@pytest.mark.asyncio
async def test_metadata_iam_client_uses_a_short_lived_workload_token() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "metadata.google.internal":
            assert request.headers["Metadata-Flavor"] == "Google"
            return httpx.Response(200, json={"access_token": "short-lived"})
        assert request.headers["Authorization"] == "Bearer short-lived"
        if request.url.path.endswith(":getIamPolicy"):
            return httpx.Response(200, json={"etag": "opaque", "bindings": []})
        assert request.url.path.endswith(":setIamPolicy")
        assert json.loads(request.content) == {"policy": {"etag": "opaque", "bindings": []}}
        return httpx.Response(200, json={})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        iam = MetadataGoogleIamPolicyApi(http=client)
        policy = await iam.get_policy("rudder-backup@example.iam.gserviceaccount.com")
        await iam.set_policy("rudder-backup@example.iam.gserviceaccount.com", policy)

    assert [request.url.host for request in requests] == [
        "metadata.google.internal",
        "iam.googleapis.com",
        "metadata.google.internal",
        "iam.googleapis.com",
    ]


@pytest.mark.asyncio
async def test_broker_binds_only_the_generated_environment_postgres_account() -> None:
    iam = FakeGoogleIam({"version": 1, "bindings": []})
    broker = GkeBackupIdentityBroker(
        project_id="example",
        backup_service_account="rudder-backup@example.iam.gserviceaccount.com",
        iam=iam,
    )

    await broker.ensure_cnpg_binding(
        namespace="rudder-shop-production", service_account_name="postgres"
    )

    assert iam.updated == [
        (
            "rudder-backup@example.iam.gserviceaccount.com",
            {
                "version": 1,
                "bindings": [
                    {
                        "role": "roles/iam.workloadIdentityUser",
                        "members": [
                            "serviceAccount:example.svc.id.goog["
                            "rudder-shop-production/postgres]"
                        ],
                    }
                ],
            },
        )
    ]


@pytest.mark.asyncio
async def test_broker_is_idempotent_for_the_same_environment_postgres_account() -> None:
    iam = FakeGoogleIam(
        {
            "etag": "opaque",
            "bindings": [
                {
                    "role": "roles/iam.workloadIdentityUser",
                    "members": [
                        "serviceAccount:example.svc.id.goog["
                        "rudder-shop-production/postgres]"
                    ],
                }
            ],
        }
    )
    broker = GkeBackupIdentityBroker(
        project_id="example",
        backup_service_account="rudder-backup@example.iam.gserviceaccount.com",
        iam=iam,
    )

    await broker.ensure_cnpg_binding(
        namespace="rudder-shop-production", service_account_name="postgres"
    )

    assert iam.updated == []


@pytest.mark.asyncio
async def test_broker_rejects_non_rudder_or_invalid_service_accounts() -> None:
    iam = FakeGoogleIam({"bindings": []})
    broker = GkeBackupIdentityBroker(
        project_id="example",
        backup_service_account="rudder-backup@example.iam.gserviceaccount.com",
        iam=iam,
    )

    with pytest.raises(ValueError, match="Rudder environment namespace"):
        await broker.ensure_cnpg_binding(namespace="default", service_account_name="postgres")
    with pytest.raises(ValueError, match="generated PostgreSQL ServiceAccount"):
        await broker.ensure_cnpg_binding(
        namespace="rudder-shop-production", service_account_name="not/a-service-account"
    )


@pytest.mark.asyncio
async def test_control_plane_client_calls_only_the_private_broker_endpoint() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"status": "bound"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        broker = HttpBackupIdentityBroker(
            base_url="http://rudder-backup-identity-broker.rudder-system",
            http=client,
        )
        await broker.ensure_cnpg_binding(
            namespace="rudder-shop-production", service_account_name="postgres"
        )

    assert len(requests) == 1
    assert str(requests[0].url) == (
        "http://rudder-backup-identity-broker.rudder-system/"
        "internal/backup-identities/cloudnativepg"
    )
    assert json.loads(requests[0].content) == {
        "namespace": "rudder-shop-production",
        "service_account_name": "postgres",
    }


def test_private_broker_rejects_a_non_environment_service_account() -> None:
    iam = FakeGoogleIam({"bindings": []})
    app = create_backup_identity_broker_app(
        project_id="example",
        backup_service_account="rudder-backup@example.iam.gserviceaccount.com",
        iam_factory=lambda: iam,
    )

    with TestClient(app) as client:
        response = client.post(
            "/internal/backup-identities/cloudnativepg",
            json={"namespace": "default", "service_account_name": "postgres"},
        )

    assert response.status_code == 422
    assert iam.updated == []


def test_private_broker_has_no_public_docs_surface() -> None:
    app = create_backup_identity_broker_app(
        project_id="example",
        backup_service_account="rudder-backup@example.iam.gserviceaccount.com",
        iam_factory=lambda: FakeGoogleIam({"bindings": []}),
    )

    with TestClient(app) as client:
        assert client.get("/docs").status_code == 404
