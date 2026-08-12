"""Tests for choosing a safe Kubernetes authentication target."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from rudder_cp.config import Settings
from rudder_cp.runtime import targets
from rudder_cp.runtime.backup_identity import HttpBackupIdentityBroker


@pytest.mark.asyncio
async def test_gke_target_uses_in_cluster_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """A production GKE control plane must never depend on a local kubeconfig."""

    called: dict[str, object] = {}

    async def from_in_cluster(runtime_settings):
        called["settings"] = runtime_settings
        return SimpleNamespace(kind="in-cluster")

    monkeypatch.setattr(targets.AsyncKubernetesApi, "from_in_cluster", from_in_cluster)

    api = await targets.load_kubernetes_client(
        Settings(
            runtime="kubernetes",
            kubernetes_target="gke",
            base_domain="rudder.invytt.com",
            kubernetes_public_domain="rudder.invytt.com",
            kubernetes_certificate_issuer="rudder-letsencrypt-prod",
            registry="asia-south1-docker.pkg.dev/invytt-2483d/rudder",
        )
    )

    assert api.kind == "in-cluster"
    assert called["settings"].local_domain == "rudder.invytt.com"


@pytest.mark.asyncio
async def test_kind_target_uses_the_explicit_kubeconfig(monkeypatch: pytest.MonkeyPatch) -> None:
    """Kind remains an explicit development target rather than a GKE fallback."""

    called: dict[str, object] = {}

    async def from_kubeconfig(runtime_settings, *, kubeconfig_path: str):
        called["settings"] = runtime_settings
        called["kubeconfig_path"] = kubeconfig_path
        return SimpleNamespace(kind="kubeconfig")

    monkeypatch.setattr(targets.AsyncKubernetesApi, "from_kubeconfig", from_kubeconfig)

    api = await targets.load_kubernetes_client(
        Settings(
            runtime="kubernetes",
            kubernetes_target="kind",
            kubernetes_kubeconfig="/tmp/kind-kubeconfig",
        )
    )

    assert api.kind == "kubeconfig"
    assert called["kubeconfig_path"] == "/tmp/kind-kubeconfig"


def test_gke_target_rejects_a_localhost_public_domain() -> None:
    """A GKE release must not accidentally publish localhost routes."""

    with pytest.raises(ValueError, match="non-localhost"):
        Settings(
            runtime="kubernetes",
            kubernetes_target="gke",
            kubernetes_public_domain="localhost",
        )


def test_gke_target_requires_system_domains_to_use_the_public_domain() -> None:
    """GKE must not create Rudder system domains under a different suffix."""

    with pytest.raises(ValueError, match="RUDDER_BASE_DOMAIN"):
        Settings(
            runtime="kubernetes",
            kubernetes_target="gke",
            base_domain="localhost",
            kubernetes_public_domain="rudder.invytt.com",
            registry="asia-south1-docker.pkg.dev/invytt-2483d/rudder",
        )


def test_gke_target_requires_a_cert_manager_cluster_issuer() -> None:
    """Production public routes must have a certificate issuer before release."""

    with pytest.raises(ValueError, match="RUDDER_KUBERNETES_CERTIFICATE_ISSUER"):
        Settings(
            runtime="kubernetes",
            kubernetes_target="gke",
            base_domain="rudder.invytt.com",
            kubernetes_public_domain="rudder.invytt.com",
            registry="asia-south1-docker.pkg.dev/invytt-2483d/rudder",
        )


def test_gke_backup_identity_is_not_mapped_until_the_platform_marks_it_ready() -> None:
    settings = Settings(
        runtime="kubernetes",
        kubernetes_target="gke",
        base_domain="rudder.invytt.com",
        kubernetes_public_domain="rudder.invytt.com",
        kubernetes_certificate_issuer="rudder-letsencrypt-prod",
        registry="asia-south1-docker.pkg.dev/invytt-2483d/rudder",
        kubernetes_backup_gcs_bucket="rudder-backups",
        kubernetes_backup_gcp_service_account="rudder-backup@example.iam.gserviceaccount.com",
    )

    runtime_settings = targets.runtime_settings_from(settings)

    assert runtime_settings.gcs_backup_configured is False


def test_gke_maps_backup_identity_only_after_the_platform_marks_it_ready() -> None:
    settings = Settings(
        runtime="kubernetes",
        kubernetes_target="gke",
        base_domain="rudder.invytt.com",
        kubernetes_public_domain="rudder.invytt.com",
        kubernetes_certificate_issuer="rudder-letsencrypt-prod",
        registry="asia-south1-docker.pkg.dev/invytt-2483d/rudder",
        kubernetes_backup_gcs_bucket="rudder-backups",
        kubernetes_backup_gcp_service_account="rudder-backup@example.iam.gserviceaccount.com",
        kubernetes_backup_gcs_identity_ready=True,
        kubernetes_backup_identity_broker_url="http://rudder-backup-identity-broker.rudder-system",
    )

    runtime_settings = targets.runtime_settings_from(settings)

    assert runtime_settings.gcs_backup_configured is True
    assert runtime_settings.backup_schedule == "0 0 2 * * *"


def test_gke_maps_its_in_cluster_api_service_to_guardrail_egress(monkeypatch) -> None:
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.112.0.1")
    settings = Settings(
        runtime="kubernetes",
        kubernetes_target="gke",
        base_domain="rudder.invytt.com",
        kubernetes_public_domain="rudder.invytt.com",
        kubernetes_certificate_issuer="rudder-letsencrypt-prod",
        registry="asia-south1-docker.pkg.dev/invytt-2483d/rudder",
    )

    assert targets.runtime_settings_from(settings).kubernetes_api_server_cidr == "10.112.0.1/32"


def test_gke_uses_the_private_backup_broker_only_when_identity_is_enabled() -> None:
    settings = Settings(
        runtime="kubernetes",
        kubernetes_target="gke",
        base_domain="rudder.invytt.com",
        kubernetes_public_domain="rudder.invytt.com",
        kubernetes_certificate_issuer="rudder-letsencrypt-prod",
        registry="asia-south1-docker.pkg.dev/invytt-2483d/rudder",
        kubernetes_backup_gcs_bucket="rudder-backups",
        kubernetes_backup_gcp_service_account="rudder-backup@example.iam.gserviceaccount.com",
        kubernetes_backup_gcs_identity_ready=True,
        kubernetes_backup_identity_broker_url="http://rudder-backup-identity-broker.rudder-system",
    )

    broker = targets.backup_identity_broker_from(settings)

    assert isinstance(broker, HttpBackupIdentityBroker)
    assert broker.base_url == "http://rudder-backup-identity-broker.rudder-system"


def test_gke_target_maps_the_required_platform_workload_pool() -> None:
    """The quota-constrained GKE topology schedules releases on platform."""

    settings = Settings(
        runtime="kubernetes",
        kubernetes_target="gke",
        base_domain="rudder.invytt.com",
        kubernetes_public_domain="rudder.invytt.com",
        kubernetes_certificate_issuer="rudder-letsencrypt-prod",
        registry="asia-south1-docker.pkg.dev/invytt-2483d/rudder",
    )

    assert targets.runtime_settings_from(settings).workload_node_selector == {
        "rudder.pool": "platform"
    }


def test_kind_target_does_not_force_gke_platform_placement() -> None:
    """Kind must remain unrestricted for the local developer workflow."""

    assert targets.runtime_settings_from(Settings()).workload_node_selector == {}


def test_gke_cloud_build_configuration_is_explicit_and_complete() -> None:
    """Production builds need managed builder inputs, never Compose BuildKit."""

    settings = Settings(
        runtime="kubernetes",
        kubernetes_target="gke",
        base_domain="rudder.invytt.com",
        kubernetes_public_domain="rudder.invytt.com",
        kubernetes_certificate_issuer="rudder-letsencrypt-prod",
        registry="asia-south1-docker.pkg.dev/invytt-2483d/rudder",
        gcp_project_id="invytt-2483d",
        gcp_region="asia-south1",
        gcp_build_source_bucket="invytt-2483d-rudder-build-source",
        gcp_build_logs_bucket="invytt-2483d-rudder-build-logs",
        gcp_build_service_account="rudder-build@invytt-2483d.iam.gserviceaccount.com",
    )

    assert settings.gke_cloud_build_configured is True
