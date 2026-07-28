"""Kubernetes translation layer for an immutable Rudder Compose release.

The control plane owns release intent.  This module deliberately owns only the
Kubernetes representation of that intent, which keeps the scheduler and
deployment history independent from a particular cluster implementation.
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from kubernetes_asyncio import client, config
from kubernetes_asyncio.client import ApiException

from rudder_cp.runtime.models import ComposeService, KubernetesRelease, dns_label


@dataclass(frozen=True, slots=True)
class RuntimeSettings:
    """Cluster settings kept separate from global application settings."""

    local_domain: str = "localhost"
    ingress_class: str = "nginx"
    readiness_timeout_seconds: int = 180
    readiness_poll_seconds: float = 2.0


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
    anti_affinity: bool = False
    topology_spread: bool = False
    rolling_update: Mapping[str, str | int] | None = None
    prometheus_enabled: bool = False
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


@dataclass(frozen=True, slots=True)
class JobSpec:
    name: str
    image: str
    command: tuple[str, ...]
    environment: Mapping[str, str]
    labels: Mapping[str, str]
    timeout_seconds: int
    retries: int


@dataclass(frozen=True, slots=True)
class ServiceSpec:
    name: str
    workload_name: str
    port: int | None
    labels: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class PublicRouteSpec:
    name: str
    host: str
    backend_service_name: str
    backend_port: int
    labels: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class KubernetesReleaseResult:
    pod_ids: Mapping[str, str]
    public_hosts: Mapping[str, str]
    operation_observed: Mapping[str, Mapping[str, object]]


class KubernetesApi(Protocol):
    async def ensure_namespace(self, namespace: str, labels: dict[str, str]) -> None: ...

    async def ensure_guardrails(self, namespace: str, labels: dict[str, str]) -> None: ...

    async def apply_service(self, namespace: str, spec: ServiceSpec) -> None: ...

    async def apply_workload(self, namespace: str, spec: WorkloadSpec) -> None: ...

    async def apply_autoscaler(self, namespace: str, spec: AutoscalerSpec) -> None: ...

    async def delete_autoscaler(self, namespace: str, name: str) -> None: ...

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

    async def promote_public_service(self, namespace: str, spec: PublicRouteSpec) -> None: ...

    async def delete_release(self, namespace: str, release_id: str) -> None: ...


class KubernetesRuntime:
    """Apply all Compose members, then promote public routes only when ready."""

    def __init__(self, api: KubernetesApi, settings: RuntimeSettings) -> None:
        self.api = api
        self.settings = settings

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
            workloads: list[tuple[ComposeService, WorkloadSpec]] = []
            operation_observed: dict[str, dict[str, object]] = {}
            for member in release.services:
                resource_name = release.resource_name(member.name)
                member_labels = {**labels, "rudder.service": dns_label(member.name)}
                operation_config, member_observed = _operation_config(member.operations)
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
                    node_selector=operation_config["node_selector"],
                    anti_affinity=operation_config["anti_affinity"],
                    topology_spread=operation_config["topology_spread"],
                    rolling_update=operation_config["rolling_update"],
                    prometheus_enabled=operation_config["prometheus_enabled"],
                    ready_replicas=operation_config["ready_replicas"],
                )
                # Keep the workload label on every associated primitive so a
                # later intent reconciliation can remove only the stale HPA /
                # CronJobs for this immutable release.  A disabled feature is
                # a deletion, not merely an omitted future render.
                member_labels = {**member_labels, "rudder.workload": resource_name}
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
                    anti_affinity=workload.anti_affinity,
                    topology_spread=workload.topology_spread,
                    rolling_update=workload.rolling_update,
                    prometheus_enabled=workload.prometheus_enabled,
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
                        name=dns_label(f"{resource_name}-schedule-{schedule_id}"),
                        schedule=str(spec.get("cron", "")),
                        image=member.image,
                        command=command,
                        environment=member.environment,
                        labels={**member_labels, "rudder.operation": dns_label(schedule_id)},
                        timeout_seconds=_int(spec.get("timeout_seconds"), 900),
                        retries=_int(spec.get("retries"), 0),
                        concurrency_policy=str(spec.get("concurrency_policy", "forbid")),
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
                pod_ids[member.name] = await self.api.wait_ready(
                    release.namespace,
                    workload,
                    timeout_seconds=self.settings.readiness_timeout_seconds,
                    poll_seconds=self.settings.readiness_poll_seconds,
                )
                await progress(f"kubernetes: {member.name} is ready\n")

            public_hosts: dict[str, str] = {}
            for member, workload in workloads:
                if not member.public or member.port is None:
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


def _command(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, (list, tuple)) or not value:
        return None
    if not all(isinstance(part, str) and part for part in value):
        return None
    return tuple(value)


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
    return (
        {
            "replicas": replicas,
            "ready_replicas": max(0, ready_replicas),
            "resources": resources,
            "node_selector": node_selector,
            "anti_affinity": placement.get("anti_affinity") is True,
            "topology_spread": placement.get("topology_spread") is True,
            "rolling_update": rolling_update,
            "prometheus_enabled": prometheus_enabled,
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
        self.batch = client.BatchV1Api(self.api_client)
        self.networking = client.NetworkingV1Api(self.api_client)

    @classmethod
    async def from_kubeconfig(
        cls, settings: RuntimeSettings, *, kubeconfig_path: str = ""
    ) -> AsyncKubernetesApi:
        if kubeconfig_path:
            await config.load_kube_config(config_file=kubeconfig_path)
        else:
            await config.load_kube_config()
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
                policy_types=["Ingress"],
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

    async def apply_service(self, namespace: str, spec: ServiceSpec) -> None:
        ports = (
            [client.V1ServicePort(name="tcp", port=spec.port, target_port=spec.port)]
            if spec.port is not None
            else []
        )
        body = client.V1Service(
            metadata=client.V1ObjectMeta(name=spec.name, labels=dict(spec.labels)),
            spec=client.V1ServiceSpec(
                type="ClusterIP",
                selector={"rudder.workload": spec.workload_name},
                ports=ports,
            ),
        )
        await self._create_or_replace(
            self.core.read_namespaced_service,
            self.core.create_namespaced_service,
            self.core.replace_namespaced_service,
            spec.name,
            body,
            namespace=namespace,
        )

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
                                    requests={"storage": "1Gi"}
                                ),
                            ),
                        )
                    ],
                ),
            )
            await self._create_or_replace(
                self.apps.read_namespaced_stateful_set,
                self.apps.create_namespaced_stateful_set,
                self.apps.replace_namespaced_stateful_set,
                spec.name,
                body,
                namespace=namespace,
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

    async def promote_public_service(self, namespace: str, spec: PublicRouteSpec) -> None:
        body = client.V1Ingress(
            metadata=client.V1ObjectMeta(name=spec.name, labels=dict(spec.labels)),
            spec=client.V1IngressSpec(
                ingress_class_name=self.settings.ingress_class,
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
        """Delete only candidate-labelled objects after an unsuccessful release."""
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
        await self.core.delete_collection_namespaced_persistent_volume_claim(
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
