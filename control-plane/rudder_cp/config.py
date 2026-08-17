"""Settings. Every knob is an env var prefixed RUDDER_ (see .env.example)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RUDDER_",
        env_file=".env",
        extra="ignore",
    )

    database_url: str = "postgresql+psycopg://rudder:rudder@localhost:5432/rudder"

    @property
    def sqlalchemy_database_url(self) -> str:
        """Return a SQLAlchemy-compatible URL for a database provider URI.

        CloudNativePG writes a standard ``postgresql://`` URI into its managed
        application Secret.  SQLAlchemy needs an explicit driver name, while
        SQLite URLs and already-explicit PostgreSQL URLs must remain unchanged.
        """

        if self.database_url.startswith("postgresql://"):
            return "postgresql+psycopg://" + self.database_url.removeprefix("postgresql://")
        if self.database_url.startswith("postgres://"):
            return "postgresql+psycopg://" + self.database_url.removeprefix("postgres://")
        return self.database_url

    # D13 — MultiFernet over a comma-separated list, first key encrypts.
    secret_keys: str = ""
    jwt_secret: str = ""
    jwt_ttl_seconds: int = 60 * 60 * 12

    # Phase 1 step 3: one user, seeded on first boot. No signup.
    admin_email: str = "you@example.com"
    admin_password: str = "change-me"

    # D2 — one token for the whole install, no per-repo model in Phase 1.
    github_token: str = ""
    github_webhook_secret: str = ""
    github_app_id: str = ""
    github_app_slug: str = ""
    github_app_private_key: str = ""
    github_app_private_key_file: str = ""
    github_oauth_client_id: str = ""
    github_oauth_client_secret: str = ""
    github_oauth_redirect_uri: str = ""
    # The OAuth callback is served by the API, but a successful browser login
    # must return to the Next.js UI rather than the API's intentionally empty
    # root route.
    web_url: str = "http://localhost:3000"
    # Full PR environments are intentionally capped: each owns its own data
    # volumes and can consume real cluster capacity.
    github_pr_environment_limit: int = 10

    # Phase 8: absence disables only non-deterministic failure diagnosis.
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    # Optional read-only operator assistant. Its absence leaves the endpoint
    # available but explicitly model-disabled.
    assistant_model: str = "gpt-4.1-mini"
    advisor_repository_root: str = ""

    @property
    def resolved_github_app_private_key(self) -> str:
        """Use a mounted PEM when configured, otherwise use the env value.

        A file path keeps a multiline GitHub App private key out of `.env` and
        lets a local install mount or rotate the key without changing the app
        configuration itself.
        """
        if self.github_app_private_key_file:
            return Path(self.github_app_private_key_file).read_text(encoding="utf-8")
        return self.github_app_private_key

    @property
    def github_app_configured(self) -> bool:
        try:
            return bool(
                self.github_app_id and self.github_app_slug and self.resolved_github_app_private_key
            )
        except OSError:
            # A missing local PEM must make the integration unavailable, not
            # turn the import dialog into a 500 response.
            return False

    # D8 — ACME cannot do HTTP-01 against localhost.
    tls_mode: Literal["off", "acme"] = "off"
    base_domain: str = "localhost"
    acme_email: str = ""

    registry: str = "localhost:5000"
    buildkit_addr: str = "tcp://registry:1234"
    docker_network: str = "rudder"

    # GKE never reaches the local Compose BuildKit service.  Its control plane
    # uploads a checked-out source archive to this private bucket and starts a
    # Cloud Build with the dedicated publisher identity instead.
    gcp_project_id: str = ""
    gcp_region: str = ""
    gcp_build_source_bucket: str = ""
    gcp_build_logs_bucket: str = ""
    gcp_build_service_account: str = ""

    @property
    def gke_cloud_build_configured(self) -> bool:
        return bool(
            self.gcp_project_id
            and self.gcp_region
            and self.gcp_build_source_bucket
            and self.gcp_build_logs_bucket
            and self.gcp_build_service_account
        )

    # Phase 3 — the control plane keeps its deployment model while swapping
    # the execution backend from a Docker agent to Kubernetes.
    runtime: Literal["docker", "kubernetes"] = "docker"
    # ``kind`` is an explicitly local developer target. ``gke`` means the
    # control plane is running inside the production cluster and must use its
    # mounted ServiceAccount token rather than an operator's kubeconfig.
    kubernetes_target: Literal["kind", "gke"] = "kind"
    kubernetes_kubeconfig: str = ""
    kubernetes_namespace_prefix: str = "rudder"
    kubernetes_ingress_class: str = "nginx"
    # The initial GKE topology has a tainted shared platform pool for both
    # Rudder's control-plane and customer workloads.  Keep this explicit so a
    # later dedicated workload-pool migration is deliberate and reviewable.
    kubernetes_workload_pool: str = "platform"
    # GKE's exact private control-plane endpoint CIDR. The platform bootstrap
    # injects this into the runtime for CNPG's required API reconciliation.
    kubernetes_api_server_endpoint_cidr: str = ""
    # GKE public routes are HTTPS-only. The issuer is installed and owned by
    # the platform bootstrap, while each release receives its own stable
    # certificate Secret through cert-manager.
    kubernetes_certificate_issuer: str = ""
    # Kept separate from ``base_domain`` so a local Kind ingress can use
    # ``localhost`` while a production control plane serves its own UI/API
    # from a different public domain.
    kubernetes_local_domain: str = "localhost"
    kubernetes_public_domain: str = ""
    kubernetes_readiness_timeout_seconds: int = 180
    # The UI must not imply that a stateful data operation works until the
    # execution cluster has the corresponding operator installed.
    kubernetes_postgres_operator: Literal["off", "cloudnativepg"] = "off"

    # A physical PostgreSQL backup is only exposed when an explicit target is
    # configured. Kind development uses the S3-compatible MinIO path below;
    # GKE uses native GCS Workload Identity and must never receive a key.
    kubernetes_backup_s3_endpoint: str = ""
    kubernetes_backup_s3_bucket: str = ""
    kubernetes_backup_s3_access_key: str = ""
    kubernetes_backup_s3_secret_key: str = ""
    kubernetes_backup_s3_region: str = "us-east-1"
    # CloudNativePG's ScheduledBackup format includes seconds. This is used
    # only after a verified object-store backup target is enabled.
    kubernetes_backup_schedule: str = "0 0 2 * * *"
    kubernetes_backup_gcs_bucket: str = ""
    kubernetes_backup_gcp_service_account: str = ""
    # Private ClusterIP endpoint of the separately-authorised backup identity
    # broker. The control plane deliberately has no IAM policy-write role.
    kubernetes_backup_identity_broker_url: str = ""
    # This is deliberately opt-in. It is set only after the private platform
    # backup-identity broker is live and verified; that broker creates and
    # verifies the exact per-environment CNPG binding during reconciliation.
    # Merely knowing a bucket and GSA must never expose a non-functional UI.
    kubernetes_backup_gcs_identity_ready: bool = False

    @property
    def kubernetes_backup_configured(self) -> bool:
        return self.kubernetes_s3_backup_configured or self.kubernetes_gcs_backup_ready

    @property
    def kubernetes_s3_backup_configured(self) -> bool:
        return bool(
            self.kubernetes_backup_s3_endpoint
            and self.kubernetes_backup_s3_bucket
            and self.kubernetes_backup_s3_access_key
            and self.kubernetes_backup_s3_secret_key
        )

    @property
    def kubernetes_gcs_backup_configured(self) -> bool:
        return bool(
            self.kubernetes_backup_gcs_bucket and self.kubernetes_backup_gcp_service_account
        )

    @property
    def kubernetes_gcs_backup_ready(self) -> bool:
        return (
            self.kubernetes_gcs_backup_configured
            and self.kubernetes_backup_gcs_identity_ready
            and bool(self.kubernetes_backup_identity_broker_url)
        )

    @model_validator(mode="after")
    def validate_kubernetes_target(self) -> Settings:
        if self.kubernetes_target != "gke":
            if (
                self.kubernetes_backup_gcs_bucket
                or self.kubernetes_backup_gcp_service_account
                or self.kubernetes_backup_identity_broker_url
                or self.kubernetes_backup_gcs_identity_ready
            ):
                raise ValueError(
                    "Native GCS Workload Identity backups require RUDDER_KUBERNETES_TARGET=gke."
                )
            return self
        if self.runtime != "kubernetes":
            raise ValueError("RUDDER_KUBERNETES_TARGET=gke requires RUDDER_RUNTIME=kubernetes.")
        if self.kubernetes_workload_pool != "platform":
            raise ValueError(
                "The current 12-vCPU GKE topology requires "
                "RUDDER_KUBERNETES_WORKLOAD_POOL=platform."
            )
        if (
            not self.kubernetes_public_domain
            or self.kubernetes_public_domain.endswith(".localhost")
            or self.kubernetes_public_domain == "localhost"
        ):
            raise ValueError(
                "RUDDER_KUBERNETES_TARGET=gke requires a non-localhost "
                "RUDDER_KUBERNETES_PUBLIC_DOMAIN."
            )
        if self.base_domain != self.kubernetes_public_domain:
            raise ValueError(
                "RUDDER_KUBERNETES_TARGET=gke requires RUDDER_BASE_DOMAIN to match "
                "RUDDER_KUBERNETES_PUBLIC_DOMAIN."
            )
        if not self.kubernetes_certificate_issuer:
            raise ValueError(
                "RUDDER_KUBERNETES_TARGET=gke requires RUDDER_KUBERNETES_CERTIFICATE_ISSUER."
            )
        if self.registry.startswith("localhost:") or self.registry.startswith("kind-registry:"):
            raise ValueError(
                "RUDDER_KUBERNETES_TARGET=gke requires an Artifact Registry hostname, "
                "not a local registry."
            )
        if any(
            (
                self.kubernetes_backup_s3_endpoint,
                self.kubernetes_backup_s3_bucket,
                self.kubernetes_backup_s3_access_key,
                self.kubernetes_backup_s3_secret_key,
            )
        ):
            raise ValueError(
                "RUDDER_KUBERNETES_TARGET=gke forbids static S3 backup credentials. "
                "Use the GCS Workload Identity backup integration instead."
            )
        if bool(self.kubernetes_backup_gcs_bucket) != bool(
            self.kubernetes_backup_gcp_service_account
        ):
            raise ValueError("GKE GCS backups require both a GCS bucket and service account.")
        if self.kubernetes_backup_gcs_identity_ready and not self.kubernetes_gcs_backup_configured:
            raise ValueError(
                "GKE GCS backups require a bucket and service account before the "
                "identity-ready flag can be enabled."
            )
        if (
            self.kubernetes_backup_gcs_identity_ready
            and not self.kubernetes_backup_identity_broker_url
        ):
            raise ValueError(
                "GKE GCS backups require RUDDER_KUBERNETES_BACKUP_IDENTITY_BROKER_URL "
                "before the identity-ready flag can be enabled."
            )
        return self

    # D3(b) — the control plane never touches Docker directly, it calls the agent.
    agent_url: str = "http://agent:9000"
    agent_shared_secret: str = "secret"

    traefik_dynamic_dir: str = "/traefik/dynamic"
    build_log_dir: str = "/var/log/rudder/builds"
    runtime_log_dir: str = "/var/log/rudder/runtime"

    # D12 — health check parameters.
    health_timeout_seconds: int = 60
    health_interval_seconds: int = 2
    health_start_grace_seconds: int = 5
    health_successes_required: int = 1

    # D10 — drain window before the old container is stopped.
    drain_seconds: int = 10

    @property
    def fernet_keys(self) -> list[str]:
        return [k.strip() for k in self.secret_keys.split(",") if k.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
