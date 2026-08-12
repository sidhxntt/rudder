"""Kubernetes translation layer for an immutable Rudder Compose release.

The control plane owns release intent.  This module deliberately owns only the
Kubernetes representation of that intent, which keeps the scheduler and
deployment history independent from a particular cluster implementation.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Protocol

from kubernetes_asyncio import client, config
from kubernetes_asyncio.client import ApiException

from rudder_cp.runtime.models import ComposeService, KubernetesRelease, dns_label


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """Cluster settings kept separate from global application settings."""

    local_domain: str = "localhost"
    ingress_class: str = "nginx"
    # Empty for local Kind. A configured issuer makes Rudder attach an
    # ingress TLS block and cert-manager annotation for every public route.
    certificate_issuer: str = ""
    readiness_timeout_seconds: int = 180
    readiness_poll_seconds: float = 2.0
    backup_s3_endpoint: str = ""
    backup_s3_bucket: str = ""
    backup_s3_access_key: str = ""
    backup_s3_secret_key: str = ""
    backup_s3_region: str = "us-east-1"
    # CloudNativePG ScheduledBackup uses a six-field cron expression including
    # seconds. The default is a daily base backup at 02:00 UTC; WAL archiving
    # provides point-in-time recovery between those base backups.
    backup_schedule: str = "0 0 2 * * *"
    # GKE's CloudNativePG integration uses a projected short-lived token via
    # Workload Identity. The account must be pre-bound to this exact CNPG
    # service account by the separately authorised platform broker.
    backup_gcs_bucket: str = ""
    backup_gcp_service_account: str = ""
    # GKE customer workloads must share the explicitly tainted platform pool
    # until project-wide CPU quota permits a dedicated workload pool. Kind
    # keeps these empty for unrestricted local scheduling.
    workload_node_selector: Mapping[str, str] = field(default_factory=dict)
    workload_tolerations: tuple[Mapping[str, str], ...] = ()
    # CNPG instance Pods reconcile themselves through the Kubernetes API. The
    # GKE control plane derives this as the exact in-cluster Service ClusterIP;
    # an empty value keeps local development's existing deny-by-default policy.
    kubernetes_api_server_cidr: str = ""

    @property
    def backup_configured(self) -> bool:
        return self.s3_backup_configured or self.gcs_backup_configured

    @property
    def s3_backup_configured(self) -> bool:
        return bool(
            self.backup_s3_endpoint
            and self.backup_s3_bucket
            and self.backup_s3_access_key
            and self.backup_s3_secret_key
        )

    @property
    def gcs_backup_configured(self) -> bool:
        return bool(self.backup_gcs_bucket and self.backup_gcp_service_account)


@dataclass(frozen=True, slots=True)
class WorkloadSpec:
    name: str
    service_name: str
    image: str
    port: int | None
    command: tuple[str, ...] | None
    environment: Mapping[str, str]
    labels: Mapping[str, str]
    stateful: bool
    volume_mount_path: str | None
    replicas: int | None = 1
    resources: Mapping[str, Mapping[str, str]] | None = None
    node_selector: Mapping[str, str] | None = None
    tolerations: tuple[Mapping[str, str], ...] = ()
    anti_affinity: bool = False
    topology_spread: bool = False
    rolling_update: Mapping[str, str | int] | None = None
    prometheus_enabled: bool = False
    # Statefully-mounted data starts at this size and can only grow. The
    # concrete PVC expansion happens separately from StatefulSet replacement,
    # because volumeClaimTemplates themselves are immutable after creation.
    storage_size_mb: int = 1024
    # The workload may be controlled by an HPA, in which case ``replicas`` is
    # intentionally unset.  Readiness still needs a concrete safety boundary:
    # never promote traffic after just one pod when the requested minimum is
    # greater than one.  Zero is a valid scale-to-zero terminal state.
    ready_replicas: int = 1


@dataclass(frozen=True, slots=True)
class AutoscalerSpec:
    name: str
    workload_name: str
    min_replicas: int
    max_replicas: int
    target_cpu_percent: int
    target_memory_percent: int | None
    labels: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class DisruptionBudgetSpec:
    """One voluntary disruption at a time for an HA stateless workload."""

    name: str
    workload_name: str
    labels: Mapping[str, str]
    min_available: int | None = None
    max_unavailable: int | None = None

    def __post_init__(self) -> None:
        if (self.min_available is None) == (self.max_unavailable is None):
            raise ValueError("a disruption budget needs exactly one availability limit")


@dataclass(frozen=True, slots=True)
class CronJobSpec:
    name: str
    schedule: str
    image: str
    command: tuple[str, ...]
    environment: Mapping[str, str]
    labels: Mapping[str, str]
    timeout_seconds: int
    retries: int
    concurrency_policy: str
    node_selector: Mapping[str, str] = field(default_factory=dict)
    tolerations: tuple[Mapping[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class JobSpec:
    name: str
    image: str
    command: tuple[str, ...]
    environment: Mapping[str, str]
    labels: Mapping[str, str]
    timeout_seconds: int
    retries: int
    node_selector: Mapping[str, str] = field(default_factory=dict)
    tolerations: tuple[Mapping[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class ServiceSpec:
    name: str
    workload_name: str
    port: int | None
    labels: Mapping[str, str]
    # A managed database's stable Rudder service is an alias to the operator's
    # endpoint rather than a selector for a Rudder-owned Pod.
    external_name: str | None = None


@dataclass(frozen=True, slots=True)
class CloudNativePostgresSpec:
    """The deliberately small CNPG contract Rudder can safely operate."""

    name: str
    service_name: str
    app_database: str
    app_user: str
    app_password: str
    storage_size_mb: int
    instances: int
    labels: Mapping[str, str]
    backup_retention_days: int | None = None
    node_selector: Mapping[str, str] = field(default_factory=dict)
    tolerations: tuple[Mapping[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class CloudNativePostgresBackupSpec:
    """One physical CNPG backup stored at the configured private object store."""

    name: str
    cluster_name: str
    retention_days: int
    labels: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class CloudNativePostgresScheduledBackupSpec:
    """One durable, operator-managed schedule for a CNPG Cluster."""

    name: str
    cluster_name: str
    schedule: str
    labels: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class PublicRouteSpec:
    name: str
    host: str
    backend_service_name: str
    backend_port: int
    labels: Mapping[str, str]
    tls_secret_name: str | None = None
    certificate_issuer: str | None = None


@dataclass(frozen=True, slots=True)
class KubernetesReleaseResult:
    pod_ids: Mapping[str, str]
    public_hosts: Mapping[str, str]
    operation_observed: Mapping[str, Mapping[str, object]]


class KubernetesApi(Protocol):
    async def ensure_namespace(self, namespace: str, labels: dict[str, str]) -> None: ...

    async def ensure_guardrails(self, namespace: str, labels: dict[str, str]) -> None: ...

    async def ensure_cnpg_backup_service_account(
        self, namespace: str, *, name: str, labels: dict[str, str]
    ) -> None: ...

    async def apply_service(self, namespace: str, spec: ServiceSpec) -> None: ...

    async def apply_cloudnative_postgres(
        self, namespace: str, spec: CloudNativePostgresSpec
    ) -> None: ...

    async def apply_cloudnative_postgres_backup(
        self, namespace: str, spec: CloudNativePostgresBackupSpec
    ) -> None: ...

    async def apply_cloudnative_postgres_scheduled_backup(
        self, namespace: str, spec: CloudNativePostgresScheduledBackupSpec
    ) -> None: ...

    async def wait_cloudnative_postgres_backup(
        self,
        namespace: str,
        spec: CloudNativePostgresBackupSpec,
        *,
        timeout_seconds: int,
        poll_seconds: float,
    ) -> bool: ...

    async def apply_workload(self, namespace: str, spec: WorkloadSpec) -> None: ...

    async def expand_stateful_storage(self, namespace: str, spec: WorkloadSpec) -> None: ...

    async def apply_autoscaler(self, namespace: str, spec: AutoscalerSpec) -> None: ...

    async def delete_autoscaler(self, namespace: str, name: str) -> None: ...

    async def apply_disruption_budget(
        self, namespace: str, spec: DisruptionBudgetSpec
    ) -> None: ...

    async def apply_cron_job(self, namespace: str, spec: CronJobSpec) -> None: ...

    async def delete_cron_jobs_for_workload(
        self, namespace: str, *, workload_name: str, release_id: str
    ) -> None: ...

    async def apply_job(self, namespace: str, spec: JobSpec) -> None: ...

    async def wait_job_complete(
        self, namespace: str, spec: JobSpec, *, timeout_seconds: int, poll_seconds: float
    ) -> bool: ...

    async def wait_ready(
        self,
        namespace: str,
        spec: WorkloadSpec,
        *,
        timeout_seconds: int,
        poll_seconds: float,
    ) -> str: ...

    async def wait_cloudnative_postgres_ready(
        self,
        namespace: str,
        spec: CloudNativePostgresSpec,
        *,
        timeout_seconds: int,
        poll_seconds: float,
    ) -> str: ...

    async def promote_public_service(self, namespace: str, spec: PublicRouteSpec) -> None: ...

    async def delete_release(self, namespace: str, release_id: str) -> None: ...


class BackupIdentityBroker(Protocol):
    """Bind the one generated CNPG service account to the backup identity."""

    async def ensure_cnpg_binding(
        self, *, namespace: str, service_account_name: str
    ) -> None: ...


class KubernetesRuntime:
    """Apply all Compose members, then promote public routes only when ready."""

    def __init__(
        self,
        api: KubernetesApi,
        settings: RuntimeSettings,
        *,
        backup_identity_broker: BackupIdentityBroker | None = None,
    ) -> None:
        self.api = api
        self.settings = settings
        self.backup_identity_broker = backup_identity_broker

    async def apply(
        self,
        release: KubernetesRelease,
        *,
        project_id: str,
        environment_id: str,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> KubernetesReleaseResult:
        async def progress(message: str) -> None:
            if on_progress is not None:
                await on_progress(message)

        labels = {
            "app.kubernetes.io/managed-by": "rudder",
            "rudder.project": dns_label(project_id),
            "rudder.environment": dns_label(environment_id),
            "rudder.release": dns_label(release.release_id),
        }
        await progress(f"kubernetes: ensuring namespace {release.namespace}\n")
        await self.api.ensure_namespace(release.namespace, labels)
        await progress("kubernetes: applying namespace guardrails\n")
        await self.api.ensure_guardrails(release.namespace, labels)

        try:
            workloads: list[tuple[ComposeService, WorkloadSpec | CloudNativePostgresSpec]] = []
            operation_observed: dict[str, dict[str, object]] = {}
            for member in release.services:
                # Immutable app candidates receive release-qualified names so
                # the old revision can keep serving until the new one is
                # ready. Stateful members are different: their PVC name is
                # derived from the StatefulSet name. Giving a database a new
                # name for every app revision silently gives it a new volume
                # and loses the persistent identity users expect.
                resource_name = (
                    dns_label(member.name)
                    if member.stateful
                    else release.resource_name(member.name)
                )
                member_labels = {**labels, "rudder.service": dns_label(member.name)}
                if member.stateful:
                    # Candidate cleanup selects by rudder.release. Persistent
                    # members must survive a failed app candidate and use a
                    # stable, non-candidate label instead.
                    member_labels["rudder.release"] = "stateful"
                operation_config, member_observed = _operation_config(member.operations)
                member_labels = {**member_labels, "rudder.workload": resource_name}
                # A caller can request additional placement constraints, but
                # target-owned constraints are last and therefore cannot be
                # bypassed by a release intent. This is what keeps customer
                # Pods off GKE's untainted system pool at the current quota.
                node_selector = {
                    **dict(operation_config["node_selector"]),
                    **dict(self.settings.workload_node_selector),
                }
                tolerations = self.settings.workload_tolerations

                # Only catalog-authored managed PostgreSQL is rendered as a
                # CloudNativePG Cluster.  A similarly named service from a
                # repository stays on the generic StatefulSet path below.
                if member.managed_database_engine == "postgres":
                    password = member.environment.get("POSTGRES_PASSWORD")
                    if not isinstance(password, str) or not password:
                        raise ValueError(
                            f"Managed PostgreSQL service {member.name} has no credential."
                        )
                    postgres = CloudNativePostgresSpec(
                        name=resource_name,
                        service_name=member.name,
                        app_database=_environment_text(member.environment, "POSTGRES_DB", "app"),
                        app_user=_environment_text(member.environment, "POSTGRES_USER", "rudder"),
                        app_password=password,
                        storage_size_mb=operation_config["storage_size_mb"],
                        instances=1 + operation_config["read_replicas"],
                        labels=member_labels,
                        backup_retention_days=(
                            _int(operation_config["backup"].get("retention_days"), 7)
                            if operation_config["backup"] is not None
                            else (7 if self.settings.backup_configured else None)
                        ),
                        node_selector=node_selector,
                        tolerations=tolerations,
                    )
                    if self.settings.gcs_backup_configured:
                        if self.backup_identity_broker is None:
                            raise RuntimeError(
                                "GCS PostgreSQL backups require the environment backup "
                                "identity broker."
                            )
                        await progress(
                            f"kubernetes: binding backup identity for {member.name}\n"
                        )
                        await self.api.ensure_cnpg_backup_service_account(
                            release.namespace,
                            name=resource_name,
                            labels=member_labels,
                        )
                        await self.backup_identity_broker.ensure_cnpg_binding(
                            namespace=release.namespace,
                            # CloudNativePG creates its default generated ServiceAccount
                            # with the Cluster's name. Keeping this stable means the
                            # broker binds one precise workload identity per environment.
                            service_account_name=resource_name,
                        )
                    await progress(
                        f"kubernetes: applying managed PostgreSQL cluster for {member.name}\n"
                    )
                    await self.api.apply_cloudnative_postgres(release.namespace, postgres)
                    if self.settings.backup_configured:
                        scheduled_backup = CloudNativePostgresScheduledBackupSpec(
                            name=dns_label(f"{resource_name}-scheduled-backup"),
                            cluster_name=resource_name,
                            schedule=self.settings.backup_schedule,
                            labels=member_labels,
                        )
                        await progress(
                            "kubernetes: configuring scheduled PostgreSQL backup for "
                            f"{member.name}\n"
                        )
                        await self.api.apply_cloudnative_postgres_scheduled_backup(
                            release.namespace, scheduled_backup
                        )
                        member_observed["scheduled_backup"] = {
                            "status": "configured",
                            "name": scheduled_backup.name,
                            "schedule": scheduled_backup.schedule,
                        }
                    await progress(
                        f"kubernetes: creating private primary endpoint for {member.name}\n"
                    )
                    await self.api.apply_service(
                        release.namespace,
                        ServiceSpec(
                            name=resource_name,
                            workload_name=resource_name,
                            port=member.port,
                            labels=member_labels,
                            external_name=f"{resource_name}-rw",
                        ),
                    )
                    await self.api.apply_service(
                        release.namespace,
                        ServiceSpec(
                            name=dns_label(f"{resource_name}-read"),
                            workload_name=resource_name,
                            port=member.port,
                            labels=member_labels,
                            external_name=f"{resource_name}-ro",
                        ),
                    )
                    member_observed["read_replicas"] = {
                        "status": "configured",
                        "replicas": operation_config["read_replicas"],
                        "endpoint": f"{dns_label(f'{resource_name}-read')}:{member.port or 5432}",
                    }
                    member_observed["storage"] = {
                        "status": "configured",
                        "size_mb": operation_config["storage_size_mb"],
                    }
                    workloads.append((member, postgres))
                    backup = operation_config["backup"]
                    if backup is not None:
                        if not self.settings.backup_configured:
                            raise RuntimeError(
                                "PostgreSQL backup was requested without a verified backup "
                                "destination configured."
                            )
                        backup_id = backup.get("operation_id")
                        if not isinstance(backup_id, str) or not backup_id:
                            raise RuntimeError(
                                "PostgreSQL backup intent has no operation identity."
                            )
                        backup_spec = CloudNativePostgresBackupSpec(
                            name=dns_label(f"{resource_name}-backup-{backup_id}"),
                            cluster_name=resource_name,
                            retention_days=_int(backup.get("retention_days"), 7),
                            labels={
                                **member_labels,
                                "rudder.operation": dns_label(backup_id),
                            },
                        )
                        await progress(
                            f"kubernetes: requesting physical PostgreSQL backup for {member.name}\n"
                        )
                        await self.api.apply_cloudnative_postgres_backup(
                            release.namespace, backup_spec
                        )
                        completed = await self.api.wait_cloudnative_postgres_backup(
                            release.namespace,
                            backup_spec,
                            timeout_seconds=self.settings.readiness_timeout_seconds,
                            poll_seconds=self.settings.readiness_poll_seconds,
                        )
                        member_observed["backup"] = {
                            "status": "completed" if completed else "failed",
                            "name": backup_spec.name,
                            "retention_days": backup_spec.retention_days,
                        }
                    operation_observed[member.name] = member_observed
                    continue
                workload = WorkloadSpec(
                    name=resource_name,
                    service_name=member.name,
                    image=member.image,
                    port=member.port,
                    command=member.command,
                    environment=member.environment,
                    labels=member_labels,
                    stateful=member.stateful,
                    volume_mount_path=member.volume_mount_path,
                    replicas=operation_config["replicas"],
                    resources=operation_config["resources"],
                    node_selector=node_selector,
                    tolerations=tolerations,
                    anti_affinity=operation_config["anti_affinity"],
                    topology_spread=operation_config["topology_spread"],
                    rolling_update=operation_config["rolling_update"],
                    prometheus_enabled=operation_config["prometheus_enabled"],
                    storage_size_mb=operation_config["storage_size_mb"],
                    ready_replicas=operation_config["ready_replicas"],
                )
                # Keep the workload label on every associated primitive so a
                # later intent reconciliation can remove only the stale HPA /
                # CronJobs for this immutable release.  A disabled feature is
                # a deletion, not merely an omitted future render.
                workload = WorkloadSpec(
                    name=workload.name,
                    service_name=workload.service_name,
                    image=workload.image,
                    port=workload.port,
                    command=workload.command,
                    environment=workload.environment,
                    labels=member_labels,
                    stateful=workload.stateful,
                    volume_mount_path=workload.volume_mount_path,
                    replicas=workload.replicas,
                    resources=workload.resources,
                    node_selector=workload.node_selector,
                    tolerations=workload.tolerations,
                    anti_affinity=workload.anti_affinity,
                    topology_spread=workload.topology_spread,
                    rolling_update=workload.rolling_update,
                    prometheus_enabled=workload.prometheus_enabled,
                    storage_size_mb=workload.storage_size_mb,
                    ready_replicas=workload.ready_replicas,
                )
                # Workers and one-shot background processes often have no
                # listening port. They still need a workload, but an empty
                # Kubernetes Service is invalid and adds no discovery value.
                if member.port is not None:
                    await progress(
                        f"kubernetes: creating private Service for {member.name}\n"
                    )
                    await self.api.apply_service(
                        release.namespace,
                        ServiceSpec(
                            name=resource_name,
                            workload_name=resource_name,
                            port=member.port,
                            labels=member_labels,
                        ),
                    )
                kind = "StatefulSet" if member.stateful else "Deployment"
                await progress(f"kubernetes: applying {kind} for {member.name}\n")
                await self.api.apply_workload(release.namespace, workload)
                requested_max_unavailable = operation_config["max_unavailable"]
                if (
                    not member.stateful
                    and (
                        workload.anti_affinity
                        or workload.topology_spread
                        or requested_max_unavailable is not None
                    )
                    and workload.ready_replicas >= 2
                ):
                    # Anti-affinity/spread is useful only when voluntary
                    # disruptions cannot drain every replica at once. Keep at
                    # least N-1 available; min_available is never zero here.
                    await progress(
                        f"kubernetes: applying disruption budget for {member.name}\n"
                    )
                    budget = DisruptionBudgetSpec(
                        name=dns_label(f"{resource_name}-pdb"),
                        workload_name=resource_name,
                        labels=member_labels,
                        max_unavailable=requested_max_unavailable,
                        min_available=(
                            None
                            if requested_max_unavailable is not None
                            else max(1, workload.ready_replicas - 1)
                        ),
                    )
                    await self.api.apply_disruption_budget(
                        release.namespace,
                        budget,
                    )
                    member_observed["availability"] = {
                        "status": "applied",
                        **(
                            {"max_unavailable": budget.max_unavailable}
                            if budget.max_unavailable is not None
                            else {"min_available": budget.min_available}
                        ),
                    }
                if member.stateful and operation_config["storage_expansion_requested"]:
                    await progress(f"kubernetes: expanding persistent storage for {member.name}\n")
                    await self.api.expand_stateful_storage(release.namespace, workload)
                autoscaling = operation_config["autoscaling"]
                if autoscaling is not None:
                    await progress(f"kubernetes: applying autoscaler for {member.name}\n")
                    await self.api.apply_autoscaler(
                        release.namespace,
                        AutoscalerSpec(
                            name=dns_label(f"{resource_name}-hpa"),
                            workload_name=resource_name,
                            min_replicas=autoscaling["min_replicas"],
                            max_replicas=autoscaling["max_replicas"],
                            target_cpu_percent=autoscaling["target_cpu_percent"],
                            target_memory_percent=autoscaling.get("target_memory_percent"),
                            labels=member_labels,
                        ),
                    )
                    member_observed["autoscaling"] = {
                        "status": "applied",
                        "min_replicas": autoscaling["min_replicas"],
                        "max_replicas": autoscaling["max_replicas"],
                    }
                else:
                    await self.api.delete_autoscaler(
                        release.namespace, dns_label(f"{resource_name}-hpa")
                    )
                    member_observed["autoscaling"] = {"status": "disabled"}

                # CronJob names are derived from operation ids, so intent
                # deletion cannot be represented by upserting the remaining
                # jobs. Prune this release/workload's scheduled jobs first,
                # then render exactly the desired schedule set.
                await self.api.delete_cron_jobs_for_workload(
                    release.namespace,
                    workload_name=resource_name,
                    release_id=release.release_id,
                )
                for schedule in operation_config["schedules"]:
                    if not isinstance(schedule, Mapping):
                        continue
                    schedule_id = str(schedule.get("operation_id", "schedule"))
                    spec = schedule.get("spec")
                    if not isinstance(spec, dict):
                        continue
                    command = _command(spec.get("command"))
                    if command is None:
                        member_observed.setdefault("schedules", {})[schedule_id] = {
                            "status": "degraded",
                            "reason": "schedule has no validated command",
                        }
                        continue
                    await progress(f"kubernetes: applying scheduled Job for {member.name}\n")
                    cron_job = CronJobSpec(
                        # CronJob appends its own Job/pod suffix, so the API
                        # reserves a stricter 52-character name limit.
                        name=dns_label(
                            f"{resource_name}-schedule-{schedule_id}", max_length=52
                        ),
                        schedule=str(spec.get("cron", "")),
                        image=member.image,
                        command=command,
                        environment=member.environment,
                        labels={**member_labels, "rudder.operation": dns_label(schedule_id)},
                        timeout_seconds=_int(spec.get("timeout_seconds"), 900),
                        retries=_int(spec.get("retries"), 0),
                        concurrency_policy=str(spec.get("concurrency_policy", "forbid")),
                        node_selector=node_selector,
                        tolerations=tolerations,
                    )
                    await self.api.apply_cron_job(release.namespace, cron_job)
                    member_observed.setdefault("schedules", {})[schedule_id] = {"status": "applied"}
                job = operation_config["job"]
                if job is not None:
                    command = _command(job.get("command"))
                    if command is None:
                        member_observed["job"] = {
                            "status": "degraded",
                            "reason": "job has no validated command",
                        }
                    else:
                        one_off = JobSpec(
                            name=dns_label(f"{resource_name}-job"),
                            image=member.image,
                            command=command,
                            environment=member.environment,
                            labels=member_labels,
                            timeout_seconds=_int(job.get("timeout_seconds"), 900),
                            retries=_int(job.get("retries"), 0),
                            node_selector=node_selector,
                            tolerations=tolerations,
                        )
                        await progress(f"kubernetes: applying one-off Job for {member.name}\n")
                        await self.api.apply_job(release.namespace, one_off)
                        completed = await self.api.wait_job_complete(
                            release.namespace,
                            one_off,
                            timeout_seconds=one_off.timeout_seconds,
                            poll_seconds=self.settings.readiness_poll_seconds,
                        )
                        member_observed["job"] = {
                            "status": "healthy" if completed else "failed",
                            "name": one_off.name,
                        }
                workloads.append((member, workload))
                operation_observed[member.name] = member_observed

            # This is the candidate safety boundary: never update an ingress
            # until every member of the release has reached readiness.
            pod_ids: dict[str, str] = {}
            for member, workload in workloads:
                await progress(f"kubernetes: waiting for {member.name} readiness\n")
                if isinstance(workload, CloudNativePostgresSpec):
                    pod_ids[member.name] = await self.api.wait_cloudnative_postgres_ready(
                        release.namespace,
                        workload,
                        timeout_seconds=self.settings.readiness_timeout_seconds,
                        poll_seconds=self.settings.readiness_poll_seconds,
                    )
                else:
                    pod_ids[member.name] = await self.api.wait_ready(
                        release.namespace,
                        workload,
                        timeout_seconds=self.settings.readiness_timeout_seconds,
                        poll_seconds=self.settings.readiness_poll_seconds,
                    )
                await progress(f"kubernetes: {member.name} is ready\n")

            public_hosts: dict[str, str] = {}
            for member, workload in workloads:
                if (
                    not member.public
                    or member.port is None
                    or isinstance(workload, CloudNativePostgresSpec)
                ):
                    continue
                host = member.public_host or (
                    f"{dns_label(member.name)}-{release.namespace}.{self.settings.local_domain}"
                )
                route = PublicRouteSpec(
                    name=dns_label(f"route-{member.name}"),
                    host=host,
                    backend_service_name=workload.name,
                    backend_port=member.port,
                    labels={**workload.labels, "rudder.route": dns_label(member.name)},
                    tls_secret_name=(
                        dns_label(f"route-{member.name}-tls")
                        if self.settings.certificate_issuer
                        else None
                    ),
                    certificate_issuer=self.settings.certificate_issuer or None,
                )
                await self.api.promote_public_service(release.namespace, route)
                await progress(
                    f"kubernetes: promoted public route for {member.name} at {host}\n"
                )
                public_hosts[member.name] = host
            return KubernetesReleaseResult(
                pod_ids=pod_ids,
                public_hosts=public_hosts,
                operation_observed=operation_observed,
            )
        except Exception as original_error:
            # Candidate resources all carry a unique release label.  Removing
            # them on any failure preserves the last live workload and, because
            # ingress promotion occurs only above, its still-working public URL.
            try:
                await progress("kubernetes: candidate failed; removing candidate resources\n")
                await self.api.delete_release(release.namespace, release.release_id)
            except Exception as cleanup_error:
                raise RuntimeError(
                    f"{original_error}; also failed to remove candidate release resources: "
                    f"{cleanup_error}"
                ) from original_error
            raise


def _int(value: object, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _environment_text(environment: Mapping[str, str], key: str, default: str) -> str:
    value = environment.get(key)
    return value if isinstance(value, str) and value else default


def _command(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, (list, tuple)) or not value:
        return None
    if not all(isinstance(part, str) and part for part in value):
        return None
    return tuple(value)


def _storage_mebibytes(value: object) -> int | None:
    """Parse the small subset of Kubernetes quantities Rudder writes itself."""
    if not isinstance(value, str):
        return None
    if value.endswith("Mi") and value[:-2].isdigit():
        return int(value[:-2])
    if value.endswith("Gi") and value[:-2].isdigit():
        return int(value[:-2]) * 1024
    return None


def _operation_config(
    operations: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, object]]:
    """Translate validated desired intent into a deliberately small runtime view.

    The control-plane validation is authoritative. These defensive checks still
    make direct runtime use fail safe: malformed intent cannot create an
    arbitrary Pod command, resource quantity, or traffic change.
    """
    resources_raw = operations.get("resources")
    resources: dict[str, dict[str, str]] | None = None
    if isinstance(resources_raw, Mapping):
        requests: dict[str, str] = {}
        limits: dict[str, str] = {}
        cpu_request = resources_raw.get("cpu_request")
        cpu_limit = resources_raw.get("cpu_limit")
        memory_request = resources_raw.get("memory_request_mb")
        memory_limit = resources_raw.get("memory_limit_mb")
        if isinstance(cpu_request, str):
            requests["cpu"] = cpu_request
        if isinstance(cpu_limit, str):
            limits["cpu"] = cpu_limit
        if isinstance(memory_request, int) and memory_request > 0:
            requests["memory"] = f"{memory_request}Mi"
        if isinstance(memory_limit, int) and memory_limit > 0:
            limits["memory"] = f"{memory_limit}Mi"
        if requests or limits:
            resources = {"requests": requests, "limits": limits}

    placement_raw = operations.get("placement")
    placement = placement_raw if isinstance(placement_raw, Mapping) else {}
    selector_raw = placement.get("node_selector", {})
    node_selector = (
        {str(key): str(value) for key, value in selector_raw.items()}
        if isinstance(selector_raw, Mapping)
        else {}
    )
    requested_max_unavailable = placement.get("max_unavailable")
    max_unavailable = (
        requested_max_unavailable
        if isinstance(requested_max_unavailable, int)
        and not isinstance(requested_max_unavailable, bool)
        and requested_max_unavailable > 0
        else None
    )
    autoscaling_raw = operations.get("autoscaling")
    autoscaling = autoscaling_raw if isinstance(autoscaling_raw, Mapping) else None
    replicas = operations.get("replicas")
    if not isinstance(replicas, int):
        replicas = 1
    if autoscaling is not None:
        # An HPA is the sole replica controller. Leaving .spec.replicas unset
        # avoids every release reconciliation fighting the HPA.
        replicas = None
    ready_replicas = (
        _int(autoscaling.get("min_replicas"), 1)
        if autoscaling is not None
        else replicas
    )

    rollout_raw = operations.get("rollout")
    rollout = rollout_raw if isinstance(rollout_raw, Mapping) else {}
    strategy = rollout.get("strategy", "rolling")
    observed: dict[str, object] = {}
    rolling_update: dict[str, str] | None = None
    if strategy == "rolling":
        # Kubernetes accepts an IntOrString here. A bare numeric string is
        # interpreted as a percentage and rejected by the API server; use an
        # actual integer for zero unavailable pods.
        rolling_update = {"max_surge": "25%", "max_unavailable": 0}
        observed["rollout"] = {"status": "applied", "strategy": "rolling"}
    elif strategy in {"blue_green", "canary"}:
        observed["rollout"] = {
            "status": "degraded",
            "reason": (
                f"{strategy.replace('_', '/')} rollout requires a traffic manager "
                "and is not enabled for this cluster"
            ),
        }

    observability_raw = operations.get("observability")
    observability = observability_raw if isinstance(observability_raw, Mapping) else {}
    prometheus_enabled = observability.get("prometheus") is True
    if prometheus_enabled or observability.get("grafana") is True:
        observed["observability"] = {
            "prometheus": "enabled" if prometheus_enabled else "disabled",
            "grafana": (
                "integration requested; no Grafana deployment is managed by Rudder"
                if observability.get("grafana") is True
                else "not requested"
            ),
        }

    schedules_raw = operations.get("schedules")
    schedules = list(schedules_raw) if isinstance(schedules_raw, list) else []
    job_raw = operations.get("last_job")
    storage_raw = operations.get("storage")
    storage_size_mb = 1024
    storage_expansion_requested = False
    if isinstance(storage_raw, Mapping):
        current_size_mb = storage_raw.get("current_size_mb")
        if isinstance(current_size_mb, int) and current_size_mb >= storage_size_mb:
            storage_size_mb = current_size_mb
        requested_size_mb = storage_raw.get("requested_size_mb")
        if isinstance(requested_size_mb, int) and requested_size_mb >= storage_size_mb:
            previous_size_mb = storage_size_mb
            storage_size_mb = requested_size_mb
            storage_expansion_requested = requested_size_mb > previous_size_mb
    read_replicas_raw = operations.get("read_replicas")
    read_replicas = 0
    if isinstance(read_replicas_raw, Mapping):
        requested_replicas = read_replicas_raw.get("replicas")
        if isinstance(requested_replicas, int) and not isinstance(requested_replicas, bool):
            read_replicas = max(0, requested_replicas)
    backup_raw = operations.get("backups")
    backup = dict(backup_raw) if isinstance(backup_raw, Mapping) else None
    return (
        {
            "replicas": replicas,
            "ready_replicas": max(0, ready_replicas),
            "resources": resources,
            "node_selector": node_selector,
            "anti_affinity": placement.get("anti_affinity") is True,
            "topology_spread": placement.get("topology_spread") is True,
            "max_unavailable": max_unavailable,
            "rolling_update": rolling_update,
            "prometheus_enabled": prometheus_enabled,
            "storage_size_mb": storage_size_mb,
            "storage_expansion_requested": storage_expansion_requested,
            "read_replicas": read_replicas,
            "backup": backup,
            "autoscaling": autoscaling,
            "schedules": schedules,
            "job": job_raw if isinstance(job_raw, Mapping) else None,
        },
        observed,
    )


class AsyncKubernetesApi:
    """Small, replace-safe kubernetes-asyncio implementation of ``KubernetesApi``."""

    def __init__(self, *, settings: RuntimeSettings) -> None:
        self.settings = settings
        # Supplying one explicit ApiClient is important: constructing each
        # typed API without it creates separate aiohttp sessions. A deploy
        # opens Core, Apps, and Networking clients, so closing only the Core
        # client leaked two TCP sessions on every release.
        self.api_client = client.ApiClient()
        self.core = client.CoreV1Api(self.api_client)
        self.apps = client.AppsV1Api(self.api_client)
        self.autoscaling = client.AutoscalingV2Api(self.api_client)
        self.policy = client.PolicyV1Api(self.api_client)
        self.batch = client.BatchV1Api(self.api_client)
        self.networking = client.NetworkingV1Api(self.api_client)
        self.storage = client.StorageV1Api(self.api_client)
        self.custom = client.CustomObjectsApi(self.api_client)

    @classmethod
    async def from_kubeconfig(
        cls, settings: RuntimeSettings, *, kubeconfig_path: str = ""
    ) -> AsyncKubernetesApi:
        if kubeconfig_path:
            await config.load_kube_config(config_file=kubeconfig_path)
        else:
            await config.load_kube_config()
        return cls(settings=settings)

    @classmethod
    async def from_in_cluster(cls, settings: RuntimeSettings) -> AsyncKubernetesApi:
        """Load the mounted ServiceAccount credentials of a GKE Pod.

        ``load_incluster_config`` is intentionally synchronous in
        kubernetes-asyncio: it only reads the token and CA files mounted into
        the Pod. Requests remain asynchronous through the shared ApiClient.
        """

        config.load_incluster_config()
        return cls(settings=settings)

    async def ensure_namespace(self, namespace: str, labels: dict[str, str]) -> None:
        body = client.V1Namespace(metadata=client.V1ObjectMeta(name=namespace, labels=labels))
        await self._create_or_replace(
            self.core.read_namespace,
            self.core.create_namespace,
            self.core.replace_namespace,
            namespace,
            body,
        )

    async def ensure_guardrails(self, namespace: str, labels: dict[str, str]) -> None:
        owner = {"app.kubernetes.io/managed-by": "rudder", **labels}
        quota = client.V1ResourceQuota(
            metadata=client.V1ObjectMeta(name="rudder-quota", labels=owner),
            spec=client.V1ResourceQuotaSpec(
                hard={"requests.cpu": "4", "requests.memory": "8Gi", "pods": "30"}
            ),
        )
        limits = client.V1LimitRange(
            metadata=client.V1ObjectMeta(name="rudder-default-limits", labels=owner),
            spec=client.V1LimitRangeSpec(
                limits=[
                    client.V1LimitRangeItem(
                        type="Container",
                        default={"cpu": "500m", "memory": "512Mi"},
                        default_request={"cpu": "250m", "memory": "256Mi"},
                    )
                ]
            ),
        )
        policy = client.V1NetworkPolicy(
            metadata=client.V1ObjectMeta(name="rudder-private-network", labels=owner),
            spec=client.V1NetworkPolicySpec(
                pod_selector=client.V1LabelSelector(),
                # Guard both directions.  The namespace label is written by
                # ``ensure_namespace`` and gives every environment its own
                # private network boundary. New external egress must be modeled
                # as an explicit, reviewed capability rather than leaking
                # through a default-allow policy.
                policy_types=["Ingress", "Egress"],
                ingress=[
                    client.V1NetworkPolicyIngressRule(
                        _from=[
                            client.V1NetworkPolicyPeer(
                                namespace_selector=client.V1LabelSelector(
                                    match_labels={
                                        "rudder.environment": labels["rudder.environment"]
                                    }
                                )
                            ),
                            # ingress-nginx terminates public traffic outside
                            # the environment namespace, so it is the only
                            # explicit cross-namespace ingress exception.
                            client.V1NetworkPolicyPeer(
                                namespace_selector=client.V1LabelSelector(
                                    match_labels={
                                        "kubernetes.io/metadata.name": "ingress-nginx"
                                    }
                                )
                            ),
                        ]
                    )
                ],
                egress=[
                    # App, worker, database and cache traffic remains private
                    # to this exact Rudder environment.
                    client.V1NetworkPolicyEgressRule(
                        to=[
                            client.V1NetworkPolicyPeer(
                                namespace_selector=client.V1LabelSelector(
                                    match_labels={
                                        "rudder.environment": labels["rudder.environment"]
                                    }
                                )
                            )
                        ]
                    ),
                    # DNS lookups are the sole cross-namespace egress path.
                    # Restrict both TCP and UDP to port 53 rather than allowing
                    # general traffic to kube-system.
                    client.V1NetworkPolicyEgressRule(
                        to=[
                            client.V1NetworkPolicyPeer(
                                namespace_selector=client.V1LabelSelector(
                                    match_labels={"kubernetes.io/metadata.name": "kube-system"}
                                )
                            )
                        ],
                        ports=[
                            client.V1NetworkPolicyPort(protocol="TCP", port=53),
                            client.V1NetworkPolicyPort(protocol="UDP", port=53),
                        ],
                    ),
                    *(
                        [
                            # CloudNativePG instances use the Kubernetes API to
                            # report and reconcile their Cluster state. Permit
                            # only the mounted in-cluster Service address, never
                            # arbitrary HTTPS egress.
                            client.V1NetworkPolicyEgressRule(
                                to=[
                                    client.V1NetworkPolicyPeer(
                                        ip_block=client.V1IPBlock(
                                            cidr=self.settings.kubernetes_api_server_cidr
                                        )
                                    )
                                ],
                                ports=[client.V1NetworkPolicyPort(protocol="TCP", port=443)],
                            )
                        ]
                        if self.settings.kubernetes_api_server_cidr
                        else []
                    ),
                ],
            ),
        )
        await self._create_or_replace(
            self.core.read_namespaced_resource_quota,
            self.core.create_namespaced_resource_quota,
            self.core.replace_namespaced_resource_quota,
            "rudder-quota",
            quota,
            namespace=namespace,
        )
        await self._create_or_replace(
            self.core.read_namespaced_limit_range,
            self.core.create_namespaced_limit_range,
            self.core.replace_namespaced_limit_range,
            "rudder-default-limits",
            limits,
            namespace=namespace,
        )
        await self._create_or_replace(
            self.networking.read_namespaced_network_policy,
            self.networking.create_namespaced_network_policy,
            self.networking.replace_namespaced_network_policy,
            "rudder-private-network",
            policy,
            namespace=namespace,
        )

    async def ensure_cnpg_backup_service_account(
        self, namespace: str, *, name: str, labels: dict[str, str]
    ) -> None:
        """Create the stable CNPG ServiceAccount before granting cloud access."""

        if not self.settings.backup_gcp_service_account:
            raise RuntimeError("CNPG backup ServiceAccount requires a GCP identity.")
        body = client.V1ServiceAccount(
            metadata=client.V1ObjectMeta(
                name=name,
                labels=dict(labels),
                annotations={
                    "iam.gke.io/gcp-service-account": self.settings.backup_gcp_service_account
                },
            )
        )
        await self._create_or_replace(
            self.core.read_namespaced_service_account,
            self.core.create_namespaced_service_account,
            self.core.replace_namespaced_service_account,
            name,
            body,
            namespace=namespace,
        )

    async def apply_service(self, namespace: str, spec: ServiceSpec) -> None:
        ports = (
            [client.V1ServicePort(name="tcp", port=spec.port, target_port=spec.port)]
            if spec.port is not None
            else []
        )
        service_spec = client.V1ServiceSpec(
            type="ExternalName" if spec.external_name else "ClusterIP",
            ports=ports,
        )
        if spec.external_name:
            service_spec.external_name = spec.external_name
        else:
            service_spec.selector = {"rudder.workload": spec.workload_name}
        body = client.V1Service(
            metadata=client.V1ObjectMeta(name=spec.name, labels=dict(spec.labels)),
            spec=service_spec,
        )
        await self._create_or_replace(
            self.core.read_namespaced_service,
            self.core.create_namespaced_service,
            self.core.replace_namespaced_service,
            spec.name,
            body,
            namespace=namespace,
        )

    async def apply_cloudnative_postgres(
        self, namespace: str, spec: CloudNativePostgresSpec
    ) -> None:
        """Create/update one CNPG primary cluster with private standby pods.

        CNPG owns the database Pods, storage lifecycle, failover and its
        ``-rw``/``-ro`` services. Rudder only supplies the small declarative
        cluster contract; no database credential is ever placed in a log.
        """
        secret_name = dns_label(f"{spec.name}-app-user")
        secret = client.V1Secret(
            metadata=client.V1ObjectMeta(name=secret_name, labels=dict(spec.labels)),
            type="kubernetes.io/basic-auth",
            data={
                "username": base64.b64encode(spec.app_user.encode("utf-8")).decode("ascii"),
                "password": base64.b64encode(spec.app_password.encode("utf-8")).decode("ascii"),
            },
        )
        await self._create_or_replace(
            self.core.read_namespaced_secret,
            self.core.create_namespaced_secret,
            self.core.replace_namespaced_secret,
            secret_name,
            secret,
            namespace=namespace,
        )
        body: dict[str, object] = {
            "apiVersion": "postgresql.cnpg.io/v1",
            "kind": "Cluster",
            "metadata": {"name": spec.name, "labels": dict(spec.labels)},
            "spec": {
                "instances": spec.instances,
                "storage": {"size": f"{spec.storage_size_mb}Mi"},
                "bootstrap": {
                    "initdb": {
                        "database": spec.app_database,
                        "owner": spec.app_user,
                        "secret": {"name": secret_name},
                    }
                },
            },
        }
        if spec.node_selector or spec.tolerations:
            cluster_spec = body["spec"]
            assert isinstance(cluster_spec, dict)
            cluster_spec["affinity"] = {
                **(
                    {"nodeSelector": dict(spec.node_selector)}
                    if spec.node_selector
                    else {}
                ),
                **(
                    {"tolerations": [dict(item) for item in spec.tolerations]}
                    if spec.tolerations
                    else {}
                ),
            }
        if self.settings.s3_backup_configured:
            backup_secret_name = dns_label(f"{spec.name}-backup-s3")
            backup_secret = client.V1Secret(
                metadata=client.V1ObjectMeta(
                    name=backup_secret_name, labels=dict(spec.labels)
                ),
                type="Opaque",
                data={
                    "ACCESS_KEY_ID": base64.b64encode(
                        self.settings.backup_s3_access_key.encode("utf-8")
                    ).decode("ascii"),
                    "ACCESS_SECRET_KEY": base64.b64encode(
                        self.settings.backup_s3_secret_key.encode("utf-8")
                    ).decode("ascii"),
                    "REGION": base64.b64encode(
                        self.settings.backup_s3_region.encode("utf-8")
                    ).decode("ascii"),
                },
            )
            await self._create_or_replace(
                self.core.read_namespaced_secret,
                self.core.create_namespaced_secret,
                self.core.replace_namespaced_secret,
                backup_secret_name,
                backup_secret,
                namespace=namespace,
            )
            cluster_backup = body["spec"]
            assert isinstance(cluster_backup, dict)
            cluster_backup["backup"] = {
                "retentionPolicy": f"{spec.backup_retention_days or 7}d",
                "barmanObjectStore": {
                    "destinationPath": (
                        f"s3://{self.settings.backup_s3_bucket}/rudder/{namespace}/{spec.name}"
                    ),
                    "endpointURL": self.settings.backup_s3_endpoint,
                    "s3Credentials": {
                        "accessKeyId": {"name": backup_secret_name, "key": "ACCESS_KEY_ID"},
                        "secretAccessKey": {
                            "name": backup_secret_name,
                            "key": "ACCESS_SECRET_KEY",
                        },
                        "region": {"name": backup_secret_name, "key": "REGION"},
                    },
                    "wal": {"compression": "gzip"},
                },
            }
        elif self.settings.gcs_backup_configured:
            cluster_backup = body["spec"]
            assert isinstance(cluster_backup, dict)
            cluster_backup["backup"] = {
                "retentionPolicy": f"{spec.backup_retention_days or 7}d",
                "barmanObjectStore": {
                    "destinationPath": (
                        f"gs://{self.settings.backup_gcs_bucket}/rudder/{namespace}/{spec.name}"
                    ),
                    "googleCredentials": {"gkeEnvironment": True},
                    "wal": {"compression": "gzip"},
                },
            }
            cluster_backup["serviceAccountTemplate"] = {
                "metadata": {
                    "annotations": {
                        "iam.gke.io/gcp-service-account": self.settings.backup_gcp_service_account
                    }
                }
            }
        try:
            existing = await self.custom.get_namespaced_custom_object(
                group="postgresql.cnpg.io",
                version="v1",
                namespace=namespace,
                plural="clusters",
                name=spec.name,
            )
        except ApiException as exc:
            if exc.status != 404:
                raise
            await self.custom.create_namespaced_custom_object(
                group="postgresql.cnpg.io",
                version="v1",
                namespace=namespace,
                plural="clusters",
                body=body,
            )
            return
        metadata = existing.get("metadata", {}) if isinstance(existing, dict) else {}
        if isinstance(metadata, dict) and isinstance(metadata.get("resourceVersion"), str):
            body["metadata"] = {
                "name": spec.name,
                "labels": dict(spec.labels),
                "resourceVersion": metadata["resourceVersion"],
            }
        await self.custom.replace_namespaced_custom_object(
            group="postgresql.cnpg.io",
            version="v1",
            namespace=namespace,
            plural="clusters",
            name=spec.name,
            body=body,
        )

    async def apply_cloudnative_postgres_backup(
        self, namespace: str, spec: CloudNativePostgresBackupSpec
    ) -> None:
        body: dict[str, object] = {
            "apiVersion": "postgresql.cnpg.io/v1",
            "kind": "Backup",
            "metadata": {"name": spec.name, "labels": dict(spec.labels)},
            "spec": {
                "cluster": {"name": spec.cluster_name},
                "method": "barmanObjectStore",
            },
        }
        try:
            existing = await self.custom.get_namespaced_custom_object(
                group="postgresql.cnpg.io",
                version="v1",
                namespace=namespace,
                plural="backups",
                name=spec.name,
            )
        except ApiException as exc:
            if exc.status != 404:
                raise
            await self.custom.create_namespaced_custom_object(
                group="postgresql.cnpg.io",
                version="v1",
                namespace=namespace,
                plural="backups",
                body=body,
            )
            return
        metadata = existing.get("metadata", {}) if isinstance(existing, dict) else {}
        if isinstance(metadata, dict) and isinstance(metadata.get("resourceVersion"), str):
            body["metadata"] = {
                "name": spec.name,
                "labels": dict(spec.labels),
                "resourceVersion": metadata["resourceVersion"],
            }
        await self.custom.replace_namespaced_custom_object(
            group="postgresql.cnpg.io",
            version="v1",
            namespace=namespace,
            plural="backups",
            name=spec.name,
            body=body,
        )

    async def apply_cloudnative_postgres_scheduled_backup(
        self, namespace: str, spec: CloudNativePostgresScheduledBackupSpec
    ) -> None:
        body: dict[str, object] = {
            "apiVersion": "postgresql.cnpg.io/v1",
            "kind": "ScheduledBackup",
            "metadata": {"name": spec.name, "labels": dict(spec.labels)},
            "spec": {
                "schedule": spec.schedule,
                "backupOwnerReference": "self",
                "cluster": {"name": spec.cluster_name},
                "method": "barmanObjectStore",
            },
        }
        try:
            existing = await self.custom.get_namespaced_custom_object(
                group="postgresql.cnpg.io",
                version="v1",
                namespace=namespace,
                plural="scheduledbackups",
                name=spec.name,
            )
        except ApiException as exc:
            if exc.status != 404:
                raise
            await self.custom.create_namespaced_custom_object(
                group="postgresql.cnpg.io",
                version="v1",
                namespace=namespace,
                plural="scheduledbackups",
                body=body,
            )
            return
        metadata = existing.get("metadata", {}) if isinstance(existing, dict) else {}
        if isinstance(metadata, dict) and isinstance(metadata.get("resourceVersion"), str):
            body["metadata"] = {
                "name": spec.name,
                "labels": dict(spec.labels),
                "resourceVersion": metadata["resourceVersion"],
            }
        await self.custom.replace_namespaced_custom_object(
            group="postgresql.cnpg.io",
            version="v1",
            namespace=namespace,
            plural="scheduledbackups",
            name=spec.name,
            body=body,
        )

    async def wait_cloudnative_postgres_backup(
        self,
        namespace: str,
        spec: CloudNativePostgresBackupSpec,
        *,
        timeout_seconds: int,
        poll_seconds: float,
    ) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            backup = await self.custom.get_namespaced_custom_object(
                group="postgresql.cnpg.io",
                version="v1",
                namespace=namespace,
                plural="backups",
                name=spec.name,
            )
            status = backup.get("status", {}) if isinstance(backup, dict) else {}
            phase = status.get("phase") if isinstance(status, dict) else None
            if phase == "completed":
                return True
            if phase in {"failed", "error"}:
                return False
            await asyncio.sleep(poll_seconds)
        return False
    async def apply_workload(self, namespace: str, spec: WorkloadSpec) -> None:
        secret_name = dns_label(f"{spec.name}-env")
        if spec.environment:
            secret = client.V1Secret(
                metadata=client.V1ObjectMeta(name=secret_name, labels=dict(spec.labels)),
                type="Opaque",
                data={
                    key: base64.b64encode(value.encode("utf-8")).decode("ascii")
                    for key, value in spec.environment.items()
                },
            )
            await self._create_or_replace(
                self.core.read_namespaced_secret,
                self.core.create_namespaced_secret,
                self.core.replace_namespaced_secret,
                secret_name,
                secret,
                namespace=namespace,
            )
        container = self._container(spec, secret_name if spec.environment else None)
        selector = {"rudder.workload": spec.name}
        pod_labels = {**dict(spec.labels), **selector}
        template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(
                labels=pod_labels,
                annotations=(
                    {
                        "prometheus.io/scrape": "true",
                        "prometheus.io/port": str(spec.port),
                    }
                    if spec.prometheus_enabled and spec.port is not None
                    else None
                ),
            ),
            spec=client.V1PodSpec(
                containers=[container],
                node_selector=dict(spec.node_selector or {}) or None,
                tolerations=[client.V1Toleration(**dict(item)) for item in spec.tolerations]
                or None,
                affinity=self._affinity(spec, selector),
                topology_spread_constraints=self._topology_spread(spec, selector),
            ),
        )
        if spec.stateful:
            if not spec.volume_mount_path:
                raise ValueError(f"Stateful service {spec.service_name} needs a volume mount path.")
            template.spec.containers[0].volume_mounts = [
                client.V1VolumeMount(name="data", mount_path=spec.volume_mount_path)
            ]
            body = client.V1StatefulSet(
                metadata=client.V1ObjectMeta(name=spec.name, labels=dict(spec.labels)),
                spec=client.V1StatefulSetSpec(
                    service_name=spec.name,
                    replicas=spec.replicas if spec.replicas is not None else 1,
                    selector=client.V1LabelSelector(match_labels=selector),
                    template=template,
                    volume_claim_templates=[
                        client.V1PersistentVolumeClaim(
                            metadata=client.V1ObjectMeta(name="data", labels=dict(spec.labels)),
                            spec=client.V1PersistentVolumeClaimSpec(
                                access_modes=["ReadWriteOnce"],
                                resources=client.V1VolumeResourceRequirements(
                                    requests={"storage": f"{spec.storage_size_mb}Mi"}
                                ),
                            ),
                        )
                    ],
                ),
            )
            # ``volumeClaimTemplates`` is immutable once a StatefulSet has
            # created its data PVC. Preserve the server's template during a
            # normal workload update; storage growth is handled by
            # ``expand_stateful_storage`` against the PVC itself.
            try:
                existing = await self.apps.read_namespaced_stateful_set(
                    name=spec.name, namespace=namespace
                )
            except ApiException as exc:
                if exc.status != 404:
                    raise
                await self.apps.create_namespaced_stateful_set(namespace=namespace, body=body)
            else:
                body.metadata.resource_version = existing.metadata.resource_version
                body.spec.volume_claim_templates = existing.spec.volume_claim_templates
                await self.apps.replace_namespaced_stateful_set(
                    name=spec.name, namespace=namespace, body=body
                )
            return
        deployment_strategy = None
        if spec.rolling_update is not None:
            deployment_strategy = client.V1DeploymentStrategy(
                type="RollingUpdate",
                rolling_update=client.V1RollingUpdateDeployment(
                    max_surge=spec.rolling_update["max_surge"],
                    max_unavailable=spec.rolling_update["max_unavailable"],
                ),
            )
        body = client.V1Deployment(
            metadata=client.V1ObjectMeta(name=spec.name, labels=dict(spec.labels)),
            spec=client.V1DeploymentSpec(
                replicas=spec.replicas if spec.replicas is not None else 1,
                selector=client.V1LabelSelector(match_labels=selector),
                template=template,
                strategy=deployment_strategy,
            ),
        )
        await self._create_or_replace(
            self.apps.read_namespaced_deployment,
            self.apps.create_namespaced_deployment,
            self.apps.replace_namespaced_deployment,
            spec.name,
            body,
            namespace=namespace,
        )

    async def expand_stateful_storage(self, namespace: str, spec: WorkloadSpec) -> None:
        """Grow an existing StatefulSet PVC after checking the StorageClass.

        The StatefulSet volume claim template is immutable. Expanding the
        actual ``data-<statefulset>-0`` PVC is the only supported Kubernetes
        path, and it is refused unless the provisioner advertises expansion.
        A first deployment has no PVC yet; its template already contains the
        requested size, so there is nothing to patch.
        """
        pvc_name = f"data-{spec.name}-0"
        try:
            pvc = await self.core.read_namespaced_persistent_volume_claim(
                pvc_name, namespace
            )
        except ApiException as exc:
            if exc.status == 404:
                return
            raise
        storage_class_name = pvc.spec.storage_class_name
        if not storage_class_name:
            raise RuntimeError(f"PVC {pvc_name} has no storage class; cannot safely expand it.")
        storage_class = await self.storage.read_storage_class(storage_class_name)
        if storage_class.allow_volume_expansion is not True:
            raise RuntimeError(
                f"StorageClass {storage_class_name} does not support volume expansion."
            )
        current = _storage_mebibytes(
            (pvc.spec.resources.requests or {}).get("storage")
        )
        if current is not None and current >= spec.storage_size_mb:
            return
        patch = client.V1PersistentVolumeClaim(
            spec=client.V1PersistentVolumeClaimSpec(
                resources=client.V1VolumeResourceRequirements(
                    requests={"storage": f"{spec.storage_size_mb}Mi"}
                )
            )
        )
        await self.core.patch_namespaced_persistent_volume_claim(
            pvc_name, namespace, patch
        )

    async def apply_autoscaler(self, namespace: str, spec: AutoscalerSpec) -> None:
        metrics = [
            client.V2MetricSpec(
                type="Resource",
                resource=client.V2ResourceMetricSource(
                    name="cpu",
                    target=client.V2MetricTarget(
                        type="Utilization", average_utilization=spec.target_cpu_percent
                    ),
                ),
            )
        ]
        if spec.target_memory_percent is not None:
            metrics.append(
                client.V2MetricSpec(
                    type="Resource",
                    resource=client.V2ResourceMetricSource(
                        name="memory",
                        target=client.V2MetricTarget(
                            type="Utilization", average_utilization=spec.target_memory_percent
                        ),
                    ),
                )
            )
        body = client.V2HorizontalPodAutoscaler(
            metadata=client.V1ObjectMeta(name=spec.name, labels=dict(spec.labels)),
            spec=client.V2HorizontalPodAutoscalerSpec(
                scale_target_ref=client.V2CrossVersionObjectReference(
                    api_version="apps/v1", kind="Deployment", name=spec.workload_name
                ),
                min_replicas=spec.min_replicas,
                max_replicas=spec.max_replicas,
                metrics=metrics,
            ),
        )
        await self._create_or_replace(
            self.autoscaling.read_namespaced_horizontal_pod_autoscaler,
            self.autoscaling.create_namespaced_horizontal_pod_autoscaler,
            self.autoscaling.replace_namespaced_horizontal_pod_autoscaler,
            spec.name,
            body,
            namespace=namespace,
        )

    async def delete_autoscaler(self, namespace: str, name: str) -> None:
        try:
            await self.autoscaling.delete_namespaced_horizontal_pod_autoscaler(
                name, namespace, body=client.V1DeleteOptions(propagation_policy="Background")
            )
        except ApiException as exc:
            if exc.status != 404:
                raise

    async def apply_disruption_budget(
        self, namespace: str, spec: DisruptionBudgetSpec
    ) -> None:
        budget: dict[str, object] = {
            "selector": client.V1LabelSelector(
                match_labels={"rudder.workload": spec.workload_name}
            )
        }
        if spec.max_unavailable is not None:
            budget["max_unavailable"] = spec.max_unavailable
        else:
            budget["min_available"] = spec.min_available
        body = client.V1PodDisruptionBudget(
            metadata=client.V1ObjectMeta(name=spec.name, labels=dict(spec.labels)),
            spec=client.V1PodDisruptionBudgetSpec(**budget),
        )
        await self._create_or_replace(
            self.policy.read_namespaced_pod_disruption_budget,
            self.policy.create_namespaced_pod_disruption_budget,
            self.policy.replace_namespaced_pod_disruption_budget,
            spec.name,
            body,
            namespace=namespace,
        )

    async def apply_cron_job(self, namespace: str, spec: CronJobSpec) -> None:
        body = client.V1CronJob(
            metadata=client.V1ObjectMeta(name=spec.name, labels=dict(spec.labels)),
            spec=client.V1CronJobSpec(
                schedule=spec.schedule,
                concurrency_policy=spec.concurrency_policy.capitalize(),
                job_template=client.V1JobTemplateSpec(
                    spec=client.V1JobSpec(
                        backoff_limit=spec.retries,
                        active_deadline_seconds=spec.timeout_seconds,
                        template=self._job_template(spec),
                    )
                ),
            ),
        )
        await self._create_or_replace(
            self.batch.read_namespaced_cron_job,
            self.batch.create_namespaced_cron_job,
            self.batch.replace_namespaced_cron_job,
            spec.name,
            body,
            namespace=namespace,
        )

    async def delete_cron_jobs_for_workload(
        self, namespace: str, *, workload_name: str, release_id: str
    ) -> None:
        selector = (
            f"rudder.workload={workload_name},"
            f"rudder.release={dns_label(release_id)}"
        )
        await self.batch.delete_collection_namespaced_cron_job(
            namespace,
            label_selector=selector,
            body=client.V1DeleteOptions(propagation_policy="Background"),
        )

    async def apply_job(self, namespace: str, spec: JobSpec) -> None:
        body = client.V1Job(
            metadata=client.V1ObjectMeta(name=spec.name, labels=dict(spec.labels)),
            spec=client.V1JobSpec(
                backoff_limit=spec.retries,
                active_deadline_seconds=spec.timeout_seconds,
                template=self._job_template(spec),
            ),
        )
        await self._create_or_replace(
            self.batch.read_namespaced_job,
            self.batch.create_namespaced_job,
            self.batch.replace_namespaced_job,
            spec.name,
            body,
            namespace=namespace,
        )

    async def wait_job_complete(
        self, namespace: str, spec: JobSpec, *, timeout_seconds: int, poll_seconds: float
    ) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            status = (await self.batch.read_namespaced_job_status(spec.name, namespace)).status
            if (status.succeeded or 0) >= 1:
                return True
            if (status.failed or 0) > spec.retries:
                return False
            await asyncio.sleep(poll_seconds)
        return False

    async def wait_ready(
        self,
        namespace: str,
        spec: WorkloadSpec,
        *,
        timeout_seconds: int,
        poll_seconds: float,
    ) -> str:
        required = spec.ready_replicas
        # A scale-to-zero service is intentionally ready without a pod.  It
        # must not wait forever or manufacture a fake running instance.
        if required == 0:
            return spec.name
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            if spec.stateful:
                status = (
                    await self.apps.read_namespaced_stateful_set_status(spec.name, namespace)
                ).status
                ready = status.ready_replicas or 0
            else:
                status = (
                    await self.apps.read_namespaced_deployment_status(spec.name, namespace)
                ).status
                ready = status.available_replicas or 0
            if ready >= required:
                pods = await self.core.list_namespaced_pod(
                    namespace, label_selector=f"rudder.workload={spec.name}"
                )
                if pods.items and pods.items[0].metadata and pods.items[0].metadata.uid:
                    return pods.items[0].metadata.uid
                return spec.name
            await asyncio.sleep(poll_seconds)
        raise RuntimeError(f"Kubernetes workload {spec.service_name} did not become ready.")

    async def wait_cloudnative_postgres_ready(
        self,
        namespace: str,
        spec: CloudNativePostgresSpec,
        *,
        timeout_seconds: int,
        poll_seconds: float,
    ) -> str:
        """Wait for an operator-reported CNPG instance and a Ready primary Pod.

        CloudNativePG normally exposes a ``Ready=True`` Cluster condition.  In
        local Kind, however, its optional TLS status probe can be unable to
        reach the Pod IP while PostgreSQL and Kubernetes readiness are both
        healthy.  ``readyInstances`` plus the elected primary Pod's Ready
        condition remains a concrete, data-plane readiness boundary in that
        situation; it is never a mere process-running check.
        """
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            cluster = await self.custom.get_namespaced_custom_object(
                group="postgresql.cnpg.io",
                version="v1",
                namespace=namespace,
                plural="clusters",
                name=spec.name,
            )
            status = cluster.get("status", {}) if isinstance(cluster, dict) else {}
            ready_instances = status.get("readyInstances", 0) if isinstance(status, dict) else 0
            conditions = status.get("conditions", []) if isinstance(status, dict) else []
            ready_condition = any(
                isinstance(condition, dict)
                and condition.get("type") == "Ready"
                and condition.get("status") == "True"
                for condition in conditions
            )
            primary_name = status.get("currentPrimary") if isinstance(status, dict) else None
            enough_instances = (
                isinstance(ready_instances, int) and ready_instances >= spec.instances
            )

            # Prefer the elected primary because it proves the write endpoint
            # behind ``<cluster>-rw`` has a Kubernetes-ready target.  This also
            # avoids waiting forever on Kind's CNPG status-probe limitation.
            if enough_instances and isinstance(primary_name, str) and primary_name:
                try:
                    primary = await self.core.read_namespaced_pod_status(
                        primary_name, namespace
                    )
                except client.exceptions.ApiException:
                    primary = None
                primary_conditions = (
                    primary.status.conditions if primary and primary.status else []
                )
                primary_ready = any(
                    condition.type == "Ready" and condition.status == "True"
                    for condition in (primary_conditions or [])
                )
                primary_uid = primary.metadata.uid if primary and primary.metadata else None
                if primary_ready:
                    return primary_uid or primary_name

            # Retain the operator's canonical Ready condition as a fallback
            # for versions that have not yet populated ``currentPrimary``.
            if enough_instances and ready_condition:
                pods = await self.core.list_namespaced_pod(
                    namespace, label_selector=f"cnpg.io/cluster={spec.name}"
                )
                if pods.items and pods.items[0].metadata and pods.items[0].metadata.uid:
                    return pods.items[0].metadata.uid
                return spec.name
            await asyncio.sleep(poll_seconds)
        raise RuntimeError(
            f"Managed PostgreSQL cluster {spec.service_name} did not become ready. "
            "Verify that the CloudNativePG operator is installed and healthy."
        )

    async def promote_public_service(self, namespace: str, spec: PublicRouteSpec) -> None:
        annotations = (
            {"cert-manager.io/cluster-issuer": spec.certificate_issuer}
            if spec.certificate_issuer
            else None
        )
        body = client.V1Ingress(
            metadata=client.V1ObjectMeta(
                name=spec.name,
                labels=dict(spec.labels),
                annotations=annotations,
            ),
            spec=client.V1IngressSpec(
                ingress_class_name=self.settings.ingress_class,
                tls=(
                    [client.V1IngressTLS(hosts=[spec.host], secret_name=spec.tls_secret_name)]
                    if spec.tls_secret_name
                    else None
                ),
                rules=[
                    client.V1IngressRule(
                        host=spec.host,
                        http=client.V1HTTPIngressRuleValue(
                            paths=[
                                client.V1HTTPIngressPath(
                                    path="/",
                                    path_type="Prefix",
                                    backend=client.V1IngressBackend(
                                        service=client.V1IngressServiceBackend(
                                            name=spec.backend_service_name,
                                            port=client.V1ServiceBackendPort(number=spec.backend_port),
                                        )
                                    ),
                                )
                            ]
                        ),
                    )
                ],
            ),
        )
        await self._create_or_replace(
            self.networking.read_namespaced_ingress,
            self.networking.create_namespaced_ingress,
            self.networking.replace_namespaced_ingress,
            spec.name,
            body,
            namespace=namespace,
        )

    async def delete_release(self, namespace: str, release_id: str) -> None:
        """Delete only disposable candidate-labelled objects after failure.

        PersistentVolumeClaims are deliberately retained. A failed candidate
        must never be able to erase user data, and the production control
        plane does not receive the RBAC permission to do so. Operators can
        perform an explicit, audited break-glass deletion outside Rudder.
        """
        selector = f"rudder.release={dns_label(release_id)}"
        delete_options = client.V1DeleteOptions(propagation_policy="Background")
        await self.apps.delete_collection_namespaced_deployment(
            namespace, label_selector=selector, body=delete_options
        )
        await self.apps.delete_collection_namespaced_stateful_set(
            namespace, label_selector=selector, body=delete_options
        )
        await self.autoscaling.delete_collection_namespaced_horizontal_pod_autoscaler(
            namespace, label_selector=selector, body=delete_options
        )
        await self.policy.delete_collection_namespaced_pod_disruption_budget(
            namespace, label_selector=selector, body=delete_options
        )
        await self.batch.delete_collection_namespaced_job(
            namespace, label_selector=selector, body=delete_options
        )
        await self.batch.delete_collection_namespaced_cron_job(
            namespace, label_selector=selector, body=delete_options
        )
        await self.core.delete_collection_namespaced_service(
            namespace, label_selector=selector, body=delete_options
        )
        await self.core.delete_collection_namespaced_secret(
            namespace, label_selector=selector, body=delete_options
        )

    async def close(self) -> None:
        """Release the shared async client session opened from kubeconfig."""
        await self.api_client.close()

    def _container(self, spec: WorkloadSpec, secret_name: str | None) -> client.V1Container:
        env = []
        if secret_name:
            env = [
                client.V1EnvVar(
                    name=key,
                    value_from=client.V1EnvVarSource(
                        secret_key_ref=client.V1SecretKeySelector(name=secret_name, key=key)
                    ),
                )
                for key in spec.environment
            ]
        port = [client.V1ContainerPort(container_port=spec.port)] if spec.port is not None else []
        probe = (
            client.V1Probe(
                tcp_socket=client.V1TCPSocketAction(port=spec.port),
                initial_delay_seconds=2,
                period_seconds=2,
                failure_threshold=30,
            )
            if spec.port is not None
            else None
        )
        return client.V1Container(
            name="app",
            image=spec.image,
            command=list(spec.command) if spec.command else None,
            ports=port,
            env=env,
            readiness_probe=probe,
            resources=client.V1ResourceRequirements(
                requests=(spec.resources or {}).get(
                    "requests", {"cpu": "250m", "memory": "256Mi"}
                ),
                limits=(spec.resources or {}).get(
                    "limits", {"cpu": "500m", "memory": "512Mi"}
                ),
            ),
        )

    def _affinity(
        self, spec: WorkloadSpec, selector: Mapping[str, str]
    ) -> client.V1Affinity | None:
        if not spec.anti_affinity:
            return None
        return client.V1Affinity(
            pod_anti_affinity=client.V1PodAntiAffinity(
                preferred_during_scheduling_ignored_during_execution=[
                    client.V1WeightedPodAffinityTerm(
                        weight=100,
                        pod_affinity_term=client.V1PodAffinityTerm(
                            topology_key="kubernetes.io/hostname",
                            label_selector=client.V1LabelSelector(match_labels=dict(selector)),
                        ),
                    )
                ]
            )
        )

    def _topology_spread(
        self, spec: WorkloadSpec, selector: Mapping[str, str]
    ) -> list[client.V1TopologySpreadConstraint] | None:
        if not spec.topology_spread:
            return None
        return [
            client.V1TopologySpreadConstraint(
                max_skew=1,
                topology_key="kubernetes.io/hostname",
                when_unsatisfiable="ScheduleAnyway",
                label_selector=client.V1LabelSelector(match_labels=dict(selector)),
            )
        ]

    def _job_template(self, spec: CronJobSpec | JobSpec) -> client.V1PodTemplateSpec:
        env = [client.V1EnvVar(name=key, value=value) for key, value in spec.environment.items()]
        return client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels=dict(spec.labels)),
            spec=client.V1PodSpec(
                restart_policy="Never",
                node_selector=dict(spec.node_selector) or None,
                tolerations=[client.V1Toleration(**dict(item)) for item in spec.tolerations]
                or None,
                containers=[
                    client.V1Container(
                        name="job",
                        image=spec.image,
                        command=list(spec.command),
                        env=env,
                    )
                ],
            ),
        )

    async def _create_or_replace(
        self,
        read: object,
        create: object,
        replace: object,
        name: str,
        body: object,
        *,
        namespace: str | None = None,
    ) -> None:
        kwargs = {"name": name}
        if namespace is not None:
            kwargs["namespace"] = namespace
        try:
            existing = await read(**kwargs)  # type: ignore[operator]
        except ApiException as exc:
            if exc.status != 404:
                raise
            if namespace is None:
                await create(body=body)  # type: ignore[operator]
            else:
                await create(namespace=namespace, body=body)  # type: ignore[operator]
            return
        metadata = getattr(existing, "metadata", None)
        body_metadata = getattr(body, "metadata", None)
        if metadata and body_metadata:
            body_metadata.resource_version = metadata.resource_version
        if namespace is None:
            await replace(name=name, body=body)  # type: ignore[operator]
        else:
            await replace(name=name, namespace=namespace, body=body)  # type: ignore[operator]
