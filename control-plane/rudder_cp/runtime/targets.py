"""Select the Kubernetes authentication target for a Rudder control plane."""

from __future__ import annotations

from rudder_cp.config import Settings
from rudder_cp.runtime.backup_identity import HttpBackupIdentityBroker
from rudder_cp.runtime.kubernetes import AsyncKubernetesApi, RuntimeSettings


def runtime_settings_from(settings: Settings) -> RuntimeSettings:
    """Translate global settings once so Kind and GKE behave identically."""

    return RuntimeSettings(
        local_domain=settings.kubernetes_public_domain or settings.kubernetes_local_domain,
        ingress_class=settings.kubernetes_ingress_class,
        certificate_issuer=(
            settings.kubernetes_certificate_issuer
            if settings.kubernetes_target == "gke"
            else ""
        ),
        readiness_timeout_seconds=settings.kubernetes_readiness_timeout_seconds,
        backup_s3_endpoint=settings.kubernetes_backup_s3_endpoint,
        backup_s3_bucket=settings.kubernetes_backup_s3_bucket,
        backup_s3_access_key=settings.kubernetes_backup_s3_access_key,
        backup_s3_secret_key=settings.kubernetes_backup_s3_secret_key,
        backup_s3_region=settings.kubernetes_backup_s3_region,
        backup_schedule=settings.kubernetes_backup_schedule,
        backup_gcs_bucket=(
            settings.kubernetes_backup_gcs_bucket
            if settings.kubernetes_target == "gke" and settings.kubernetes_gcs_backup_ready
            else ""
        ),
        backup_gcp_service_account=(
            settings.kubernetes_backup_gcp_service_account
            if settings.kubernetes_target == "gke" and settings.kubernetes_gcs_backup_ready
            else ""
        ),
        workload_node_selector=(
            {"rudder.pool": settings.kubernetes_workload_pool}
            if settings.kubernetes_target == "gke"
            else {}
        ),
        workload_tolerations=(
            (
                {
                    "key": "rudder.pool",
                    "operator": "Equal",
                    "value": "platform",
                    "effect": "NoSchedule",
                },
            )
            if settings.kubernetes_target == "gke"
            else ()
        ),
        kubernetes_api_server_endpoint_cidr=(
            settings.kubernetes_api_server_endpoint_cidr
            if settings.kubernetes_target == "gke"
            else ""
        ),
    )


def backup_identity_broker_from(settings: Settings) -> HttpBackupIdentityBroker | None:
    """Use the private broker only for a verified GKE backup integration."""

    if settings.kubernetes_target != "gke" or not settings.kubernetes_gcs_backup_ready:
        return None
    return HttpBackupIdentityBroker(
        base_url=settings.kubernetes_backup_identity_broker_url,
    )


async def load_kubernetes_client(settings: Settings) -> AsyncKubernetesApi:
    """Load local kubeconfig only for Kind; GKE uses in-cluster identity."""

    runtime_settings = runtime_settings_from(settings)
    if settings.kubernetes_target == "gke":
        return await AsyncKubernetesApi.from_in_cluster(runtime_settings)
    return await AsyncKubernetesApi.from_kubeconfig(
        runtime_settings,
        kubeconfig_path=settings.kubernetes_kubeconfig,
    )
