"""Static contracts for the production control-plane bootstrap path."""

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_control_plane_uses_cnpg_application_credentials_and_runtime_secret() -> None:
    """The API must not boot against localhost or bake operational secrets into Git."""

    manifest = (REPOSITORY_ROOT / "infra/kubernetes/platform/control-plane.yaml").read_text(
        encoding="utf-8"
    )

    assert "name: rudder-control-plane-db-app" in manifest
    assert "key: uri" in manifest
    assert "secretRef:" in manifest
    assert "name: rudder-control-plane-runtime" in manifest
    assert manifest.count("path: /healthz") == 2
    assert "RUDDER_KUBERNETES_TARGET" in manifest
    assert "RUDDER_KUBERNETES_PUBLIC_DOMAIN" in manifest


def test_platform_declares_a_replicated_cnpg_database_and_migration_job() -> None:
    """Schema migration has to complete before the control-plane rolls out."""

    database_path = REPOSITORY_ROOT / "infra/kubernetes/platform/control-plane-database.yaml"
    migration_path = REPOSITORY_ROOT / "infra/kubernetes/platform/control-plane-migration.yaml"
    database = database_path.read_text(encoding="utf-8")
    migration = migration_path.read_text(encoding="utf-8")

    assert "kind: Cluster" in database
    assert "name: rudder-control-plane-db" in database
    assert "instances: 3" in database
    assert "dataChecksums: true" in database
    assert "rudder.pool: platform" in database
    assert "effect: NoSchedule" in database

    assert "kind: Job" in migration
    assert '"alembic", "upgrade", "head"' in migration
    assert "name: rudder-control-plane-db-app" in migration
    assert "key: uri" in migration


def test_external_secret_sync_has_a_dedicated_least_privilege_identity() -> None:
    """A platform secret sync must not borrow the node or control-plane identity."""

    identity = (REPOSITORY_ROOT / "infra/gcp/terraform/identity.tf").read_text(encoding="utf-8")
    secrets = (REPOSITORY_ROOT / "infra/kubernetes/platform/external-secrets.yaml").read_text(
        encoding="utf-8"
    )
    bootstrap = (REPOSITORY_ROOT / "infra/gcp/scripts/bootstrap-platform.sh").read_text(
        encoding="utf-8"
    )

    assert 'resource "google_service_account" "secret_sync"' in identity
    assert 'resource "google_secret_manager_secret" "control_plane_runtime"' in identity
    assert (
        'resource "google_secret_manager_secret_iam_member" '
        '"control_plane_runtime_reader"' in identity
    )
    assert "rudder-system/rudder-secret-sync" in identity
    assert "roles/secretmanager.secretAccessor" in identity

    assert "name: rudder-secret-sync" in secrets
    assert "kind: SecretStore" in secrets
    assert "kind: ExternalSecret" in secrets
    assert "RUDDER_CONTROL_PLANE_SECRET_NAME" in secrets
    assert "RUDDER_SECRET_SYNC_GSA" in secrets
    assert "RUDDER_SECRET_SYNC_GSA" in bootstrap
    assert "RUDDER_CONTROL_PLANE_SECRET_NAME" in bootstrap


def test_bootstrap_waits_for_database_secret_migration_and_secret_sync() -> None:
    """Readiness of Helm controllers is not readiness of the Rudder API."""

    bootstrap = (REPOSITORY_ROOT / "infra/gcp/scripts/bootstrap-platform.sh").read_text(
        encoding="utf-8"
    )

    assert "control-plane-database.yaml" in bootstrap
    assert "cluster.postgresql.cnpg.io/rudder-control-plane-db" in bootstrap
    assert "control-plane-migration.yaml" in bootstrap
    assert "job/rudder-control-plane-migrate" in bootstrap
    assert "secret/rudder-control-plane-runtime" in bootstrap
    assert bootstrap.index("control-plane-migration.yaml") < bootstrap.index("control-plane.yaml")


def test_bootstrap_fails_closed_for_non_immutable_or_out_of_zone_inputs() -> None:
    """A production rollout cannot accept floating images or DNS drift."""

    bootstrap = (REPOSITORY_ROOT / "infra/gcp/scripts/bootstrap-platform.sh").read_text(
        encoding="utf-8"
    )

    assert '"@sha256:"' in bootstrap
    assert "expected_registry_prefix" in bootstrap
    assert "RUDDER_CONTROL_PLANE_HOST must be a hostname below" in bootstrap
    assert "RUDDER_KUBERNETES_PUBLIC_DOMAIN must equal or be below" in bootstrap
    assert "gcloud secrets describe" in bootstrap


def test_makefile_exposes_safe_gke_operator_entrypoints() -> None:
    """Operators should not need to rediscover ad-hoc production commands."""

    makefile = (REPOSITORY_ROOT / "Makefile").read_text(encoding="utf-8")

    assert "gke-preflight:" in makefile
    assert "gke-bootstrap:" in makefile
    assert "gke-verify:" in makefile
    assert "infra/gcp/scripts/preflight-gke.sh" in makefile
    assert "infra/gcp/scripts/bootstrap-platform.sh" in makefile


def test_control_plane_image_installs_the_locked_runtime_dependency_graph() -> None:
    """The GKE artifact may not resolve a different package set from CI."""

    dockerfile = (REPOSITORY_ROOT / "control-plane/Dockerfile").read_text(encoding="utf-8")

    assert 'uv sync --locked --no-dev --no-install-project' in dockerfile
    assert "RUN uv sync --locked --no-dev" in dockerfile
    assert 'ENV PATH="/opt/rudder-venv/bin:${PATH}"' in dockerfile
    assert 'pip install --no-cache-dir -e ".[dev]"' not in dockerfile
