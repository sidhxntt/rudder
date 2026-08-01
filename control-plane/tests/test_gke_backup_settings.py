"""Production backup configuration must not fall back to static cloud keys."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from rudder_cp.config import Settings


def _gke_settings(**overrides: str) -> Settings:
    values = {
        "runtime": "kubernetes",
        "kubernetes_target": "gke",
        "kubernetes_public_domain": "rudder.example.com",
        "base_domain": "rudder.example.com",
        "kubernetes_certificate_issuer": "rudder-acme",
        "registry": "asia-south1-docker.pkg.dev/example/rudder/images",
    }
    values.update(overrides)
    return Settings(**values)


def test_gke_rejects_static_s3_backup_credentials() -> None:
    """GKE database pods must use workload identity, never S3 access keys."""
    with pytest.raises(ValidationError, match="static S3 backup credentials"):
        _gke_settings(
            kubernetes_backup_s3_endpoint="https://storage.googleapis.com",
            kubernetes_backup_s3_bucket="rudder-backups",
            kubernetes_backup_s3_access_key="should-not-be-accepted",
            kubernetes_backup_s3_secret_key="should-not-be-accepted",
        )


def test_kind_keeps_private_minio_backup_credentials_available() -> None:
    settings = Settings(
        runtime="kubernetes",
        kubernetes_target="kind",
        kubernetes_backup_s3_endpoint="http://minio:9000",
        kubernetes_backup_s3_bucket="rudder-backups",
        kubernetes_backup_s3_access_key="minio",
        kubernetes_backup_s3_secret_key="local-only",
    )

    assert settings.kubernetes_backup_configured is True


def test_gke_accepts_native_gcs_backup_identity_without_static_credentials() -> None:
    settings = _gke_settings(
        kubernetes_backup_gcs_bucket="rudder-backups",
        kubernetes_backup_gcp_service_account="rudder-backup@example.iam.gserviceaccount.com",
    )

    # Configuring the desired identity is not enough to expose a live backup
    # control: the platform's narrowly-authorised broker must first bind the
    # generated CNPG KSA to this GSA.
    assert settings.kubernetes_gcs_backup_configured is True
    assert settings.kubernetes_backup_configured is False


def test_gke_enables_backups_only_after_identity_binding_is_verified() -> None:
    settings = _gke_settings(
        kubernetes_backup_gcs_bucket="rudder-backups",
        kubernetes_backup_gcp_service_account="rudder-backup@example.iam.gserviceaccount.com",
        kubernetes_backup_gcs_identity_ready=True,
        kubernetes_backup_identity_broker_url="http://rudder-backup-identity-broker.rudder-system",
    )

    assert settings.kubernetes_backup_configured is True


@pytest.mark.parametrize(
    "overrides",
    (
        {"kubernetes_backup_gcs_bucket": "rudder-backups"},
        {
            "kubernetes_backup_gcp_service_account": (
                "rudder-backup@example.iam.gserviceaccount.com"
            )
        },
    ),
)
def test_gke_requires_a_complete_gcs_workload_identity_backup_config(
    overrides: dict[str, str],
) -> None:
    with pytest.raises(ValidationError, match="GCS bucket and service account"):
        _gke_settings(**overrides)


def test_gke_rejects_an_identity_readiness_attestation_without_identity_config() -> None:
    with pytest.raises(ValidationError, match="identity-ready flag"):
        _gke_settings(kubernetes_backup_gcs_identity_ready=True)


def test_gke_rejects_an_identity_readiness_attestation_without_private_broker() -> None:
    with pytest.raises(ValidationError, match="BACKUP_IDENTITY_BROKER_URL"):
        _gke_settings(
            kubernetes_backup_gcs_bucket="rudder-backups",
            kubernetes_backup_gcp_service_account="rudder-backup@example.iam.gserviceaccount.com",
            kubernetes_backup_gcs_identity_ready=True,
        )
