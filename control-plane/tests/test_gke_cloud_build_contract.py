"""Static contract for the managed GKE image-builder boundary."""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_gke_platform_declares_a_least_privilege_cloud_build_path() -> None:
    """Production must not depend on the local Compose BuildKit service."""

    services = (REPOSITORY_ROOT / "infra/gcp/terraform/services.tf").read_text(encoding="utf-8")
    storage = (REPOSITORY_ROOT / "infra/gcp/terraform/storage.tf").read_text(encoding="utf-8")
    identity = (REPOSITORY_ROOT / "infra/gcp/terraform/identity.tf").read_text(encoding="utf-8")
    manifest = (REPOSITORY_ROOT / "infra/kubernetes/platform/control-plane.yaml").read_text(
        encoding="utf-8"
    )
    bootstrap = (REPOSITORY_ROOT / "infra/gcp/scripts/bootstrap-platform.sh").read_text(
        encoding="utf-8"
    )

    assert '"cloudbuild.googleapis.com"' in services
    assert 'resource "google_storage_bucket" "build_sources"' in storage
    assert 'resource "google_storage_bucket" "build_logs"' in storage
    assert 'role    = "roles/cloudbuild.builds.editor"' in identity
    assert 'role               = "roles/iam.serviceAccountUser"' in identity
    assert 'resource "google_storage_bucket_iam_member" "runtime_build_source_writer"' in storage
    assert 'resource "google_storage_bucket_iam_member" "build_logs_writer"' in storage
    build_logs_binding = storage.split(
        'resource "google_storage_bucket_iam_member" "build_logs_writer" {', 1
    )[1].split("}\n", 1)[0]
    assert 'bucket = google_storage_bucket.build_logs.name' in build_logs_binding
    assert 'role   = "roles/storage.admin"' in build_logs_binding
    assert "RUDDER_GCP_BUILD_SOURCE_BUCKET" in manifest
    assert "RUDDER_GCP_BUILD_LOGS_BUCKET" in manifest
    assert "RUDDER_GCP_BUILD_SERVICE_ACCOUNT" in manifest
    assert "RUDDER_GCP_BUILD_SOURCE_BUCKET" in bootstrap
    assert "RUDDER_GCP_BUILD_LOGS_BUCKET" in bootstrap
    assert "RUDDER_GCP_BUILD_SERVICE_ACCOUNT" in bootstrap


def test_control_plane_image_has_a_cloud_build_architecture_default() -> None:
    """Cloud Build's Docker builder must not produce a ``linux-.tar.gz`` URL."""

    dockerfile = (REPOSITORY_ROOT / "control-plane/Dockerfile").read_text(encoding="utf-8")

    assert "ARG TARGETARCH=amd64" in dockerfile


def test_platform_rbac_can_remove_only_disposable_candidate_resources() -> None:
    """Failed candidate releases use labelled delete-collection calls."""
    rbac = (REPOSITORY_ROOT / "infra/kubernetes/platform/rbac.yaml").read_text(
        encoding="utf-8"
    )

    for resource in (
        "configmaps",
        "secrets",
        "services",
        "deployments",
        "statefulsets",
        "jobs",
        "cronjobs",
        "horizontalpodautoscalers",
        "poddisruptionbudgets",
    ):
        assert resource in rbac
    assert '"deletecollection"' in rbac


def test_platform_rbac_can_read_workload_status_for_readiness() -> None:
    """The reconciler must observe status without gaining broad pod mutation rights."""
    rbac = (REPOSITORY_ROOT / "infra/kubernetes/platform/rbac.yaml").read_text(
        encoding="utf-8"
    )

    assert 'resources: ["pods/status"]' in rbac
    assert 'resources: ["deployments/status", "statefulsets/status"]' in rbac
    assert 'resources: ["jobs/status"]' in rbac


def test_platform_rbac_can_read_bounded_pod_logs_and_metrics() -> None:
    """The control plane must observe GKE workloads without node credentials."""
    rbac = (REPOSITORY_ROOT / "infra/kubernetes/platform/rbac.yaml").read_text(
        encoding="utf-8"
    )

    assert 'resources: ["pods/log"]' in rbac
    assert 'apiGroups: ["metrics.k8s.io"]' in rbac
