"""Keep production backup identity scoped to the actual environment workload."""

from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_terraform_does_not_bind_backup_identity_to_the_platform_namespace() -> None:
    """CNPG database Pods run in environment namespaces, never rudder-system."""
    identity = (REPOSITORY_ROOT / "infra/gcp/terraform/identity.tf").read_text(
        encoding="utf-8"
    )

    assert 'google_service_account_iam_member" "backup_workload_identity"' not in identity
    assert "rudder-system/rudder-cnpg-backup" not in identity


def test_only_the_separate_broker_can_manage_backup_identity_policy() -> None:
    identity = (REPOSITORY_ROOT / "infra/gcp/terraform/identity.tf").read_text(
        encoding="utf-8"
    )

    assert 'google_service_account_iam_member" "runtime_manages_backup_identity"' not in identity
    assert 'google_service_account" "backup_identity_broker"' in identity
    assert 'google_project_iam_custom_role" "backup_identity_broker"' in identity
    assert '"iam.serviceAccounts.setIamPolicy"' in identity
    assert "google_service_account.backup_identity_broker.email" in identity
    broker_binding = identity.split(
        'resource "google_project_iam_member" "backup_identity_broker_policy_writer"', 1
    )[1].split("}", 1)[0]
    assert "google_service_account.runtime.email" not in broker_binding


def test_platform_manifests_do_not_advertise_a_nonfunctional_fixed_backup_identity() -> None:
    """A CNPG backup identity must be created per environment, never globally."""
    cloudnativepg = (REPOSITORY_ROOT / "infra/kubernetes/platform/cloudnativepg.yaml").read_text(
        encoding="utf-8"
    )
    rbac = (REPOSITORY_ROOT / "infra/kubernetes/platform/rbac.yaml").read_text(
        encoding="utf-8"
    )
    bootstrap = (REPOSITORY_ROOT / "infra/gcp/scripts/bootstrap-platform.sh").read_text(
        encoding="utf-8"
    )

    assert "name: rudder-cnpg-backup" not in cloudnativepg
    assert "backupServiceAccount:" not in cloudnativepg
    assert "name: rudder-cnpg-backup" not in rbac
    assert '"${RUDDER_BACKUP_GSA:?Set RUDDER_BACKUP_GSA' in bootstrap
    assert "backup-identity-broker.yaml" in bootstrap


def test_runtime_rbac_can_create_only_the_environment_service_account_contract() -> None:
    rbac = (REPOSITORY_ROOT / "infra/kubernetes/platform/rbac.yaml").read_text(
        encoding="utf-8"
    )

    assert 'resources: ["configmaps", "secrets", "services", "serviceaccounts"]' in rbac


def test_broker_has_a_separate_private_service_account_and_network_boundary() -> None:
    broker = (REPOSITORY_ROOT / "infra/kubernetes/platform/backup-identity-broker.yaml").read_text(
        encoding="utf-8"
    )

    assert "name: rudder-backup-identity-broker" in broker
    assert "type: ClusterIP" in broker
    assert "app.kubernetes.io/name: rudder-control-plane" in broker
    assert "RUDDER_KUBERNETES_BACKUP_GCP_SERVICE_ACCOUNT" in broker
    # Calico clusters require GKE Workload Identity's exact metadata proxy
    # address and ports before the broker can call IAM over HTTPS.
    assert "cidr: 169.254.169.252/32" in broker
    assert "port: 987" in broker
    assert "port: 988" in broker
    # GKE's node-local DNS intercepts the cluster DNS service address.
    assert "cidr: 10.112.0.10/32" in broker
    assert "cidr: 169.254.20.10/32" in broker
    assert "envFrom:" not in broker
