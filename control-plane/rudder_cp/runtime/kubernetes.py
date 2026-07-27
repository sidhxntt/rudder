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
from typing import Protocol

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


class KubernetesApi(Protocol):
    async def ensure_namespace(self, namespace: str, labels: dict[str, str]) -> None: ...

    async def ensure_guardrails(self, namespace: str, labels: dict[str, str]) -> None: ...

    async def apply_service(self, namespace: str, spec: ServiceSpec) -> None: ...

    async def apply_workload(self, namespace: str, spec: WorkloadSpec) -> None: ...

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
            for member in release.services:
                resource_name = release.resource_name(member.name)
                member_labels = {**labels, "rudder.service": dns_label(member.name)}
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
                workloads.append((member, workload))

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
                host = f"{dns_label(member.name)}-{release.namespace}.{self.settings.local_domain}"
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
            return KubernetesReleaseResult(pod_ids=pod_ids, public_hosts=public_hosts)
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
            metadata=client.V1ObjectMeta(labels=pod_labels),
            spec=client.V1PodSpec(containers=[container]),
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
                    replicas=1,
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
        body = client.V1Deployment(
            metadata=client.V1ObjectMeta(name=spec.name, labels=dict(spec.labels)),
            spec=client.V1DeploymentSpec(
                replicas=1,
                selector=client.V1LabelSelector(match_labels=selector),
                template=template,
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

    async def wait_ready(
        self,
        namespace: str,
        spec: WorkloadSpec,
        *,
        timeout_seconds: int,
        poll_seconds: float,
    ) -> str:
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
            if ready >= 1:
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
                requests={"cpu": "250m", "memory": "256Mi"},
                limits={"cpu": "500m", "memory": "512Mi"},
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
