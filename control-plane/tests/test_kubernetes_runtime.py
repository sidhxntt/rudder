from types import SimpleNamespace

import pytest

from rudder_cp.runtime.kubernetes import (
    AsyncKubernetesApi,
    CloudNativePostgresBackupSpec,
    CloudNativePostgresSpec,
    KubernetesRuntime,
    RuntimeSettings,
    WorkloadSpec,
)
from rudder_cp.runtime.models import ComposeService, KubernetesRelease


def test_release_names_are_dns_safe_and_namespace_scoped() -> None:
    release = KubernetesRelease(
        namespace="rudder-shop-production",
        release_id="AABBCCDD-1234-5678-9ABC-DEF012345678",
        services=(
            ComposeService(
                name="web_api",
                image="kind-registry:5000/web@sha256:abc",
                port=3000,
            ),
        ),
    )

    assert release.namespace == "rudder-shop-production"
    assert release.resource_name("web_api") == "web-api-aabbccdd"


class FakeKubernetesApi:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    async def ensure_namespace(self, namespace: str, labels: dict[str, str]) -> None:
        self.calls.append(("namespace", (namespace, labels)))

    async def ensure_guardrails(self, namespace: str, labels: dict[str, str]) -> None:
        self.calls.append(("guardrails", namespace))

    async def apply_service(self, namespace: str, spec: object) -> None:
        self.calls.append(("service", spec))

    async def apply_workload(self, namespace: str, spec: object) -> None:
        self.calls.append(("workload", spec))

    async def apply_cloudnative_postgres(
        self, namespace: str, spec: object
    ) -> None:
        self.calls.append(("cloudnative-postgres", spec))

    async def apply_cloudnative_postgres_backup(
        self, namespace: str, spec: object
    ) -> None:
        self.calls.append(("cloudnative-postgres-backup", spec))

    async def wait_cloudnative_postgres_backup(
        self,
        namespace: str,
        spec: object,
        *,
        timeout_seconds: int,
        poll_seconds: float,
    ) -> bool:
        self.calls.append(("cloudnative-postgres-backup-ready", spec))
        return True

    async def expand_stateful_storage(self, namespace: str, spec: object) -> None:
        self.calls.append(("storage", spec))

    async def apply_autoscaler(self, namespace: str, spec: object) -> None:
        self.calls.append(("autoscaler", spec))

    async def delete_autoscaler(self, namespace: str, name: str) -> None:
        self.calls.append(("delete-autoscaler", name))

    async def apply_disruption_budget(self, namespace: str, spec: object) -> None:
        self.calls.append(("pdb", spec))

    async def apply_cron_job(self, namespace: str, spec: object) -> None:
        self.calls.append(("cronjob", spec))

    async def delete_cron_jobs_for_workload(
        self, namespace: str, *, workload_name: str, release_id: str
    ) -> None:
        self.calls.append(("delete-cronjobs", (workload_name, release_id)))

    async def apply_job(self, namespace: str, spec: object) -> None:
        self.calls.append(("job", spec))

    async def wait_job_complete(
        self, namespace: str, spec: object, *, timeout_seconds: int, poll_seconds: float
    ) -> bool:
        self.calls.append(("job-complete", spec))
        return True

    async def wait_ready(
        self,
        namespace: str,
        spec: object,
        *,
        timeout_seconds: int,
        poll_seconds: float,
    ) -> str:
        self.calls.append(("ready", spec))
        return f"pod-{spec.name}"

    async def wait_cloudnative_postgres_ready(
        self,
        namespace: str,
        spec: object,
        *,
        timeout_seconds: int,
        poll_seconds: float,
    ) -> str:
        self.calls.append(("cloudnative-postgres-ready", spec))
        return f"pod-{spec.name}-1"

    async def promote_public_service(self, namespace: str, spec: object) -> None:
        self.calls.append(("ingress", spec))

    async def delete_release(self, namespace: str, release_id: str) -> None:
        self.calls.append(("cleanup", (namespace, release_id)))


@pytest.mark.asyncio
async def test_runtime_creates_private_stateful_service_and_public_web_after_readiness() -> None:
    api = FakeKubernetesApi()
    runtime = KubernetesRuntime(api, RuntimeSettings(local_domain="localhost"))
    release = KubernetesRelease(
        namespace="rudder-shop-production",
        release_id="aabbccdd-1234-5678-9abc-def012345678",
        services=(
            ComposeService(name="web", image="registry/web@sha256:1", port=3000, public=True),
            ComposeService(
                name="postgres",
                image="postgres:16-alpine",
                port=5432,
                stateful=True,
                volume_mount_path="/var/lib/postgresql/data",
            ),
        ),
    )

    result = await runtime.apply(release, project_id="project", environment_id="environment")

    workloads = [value for name, value in api.calls if name == "workload"]
    assert [workload.name for workload in workloads] == ["web-aabbccdd", "postgres"]
    assert workloads[0].stateful is False
    assert workloads[1].stateful is True
    assert workloads[1].volume_mount_path == "/var/lib/postgresql/data"
    assert [name for name, _ in api.calls].index("ingress") > [name for name, _ in api.calls].index(
        "ready"
    )
    assert result.pod_ids == {"web": "pod-web-aabbccdd", "postgres": "pod-postgres"}
    assert result.public_hosts == {"web": "web-rudder-shop-production.localhost"}


@pytest.mark.asyncio
async def test_rudder_managed_postgres_becomes_a_private_cnpg_cluster_with_standbys() -> None:
    """Read replicas are PostgreSQL standbys, never generic Postgres copies."""
    api = FakeKubernetesApi()
    runtime = KubernetesRuntime(api, RuntimeSettings(local_domain="localhost"))
    release = KubernetesRelease(
        namespace="rudder-shop-production",
        release_id="aabbccdd-1234-5678-9abc-def012345678",
        services=(
            ComposeService(
                name="postgres",
                image="postgres:16-alpine",
                port=5432,
                stateful=True,
                volume_mount_path="/var/lib/postgresql/data",
                managed_database_engine="postgres",
                environment={
                    "POSTGRES_DB": "app",
                    "POSTGRES_USER": "rudder",
                    "POSTGRES_PASSWORD": "not-in-logs",
                },
                operations={
                    "storage": {"current_size_mb": 1024, "requested_size_mb": 2048},
                    "read_replicas": {"replicas": 2},
                },
            ),
        ),
    )

    result = await runtime.apply(release, project_id="project", environment_id="environment")

    postgres = next(value for name, value in api.calls if name == "cloudnative-postgres")
    assert isinstance(postgres, CloudNativePostgresSpec)
    assert postgres.name == "postgres"
    assert postgres.instances == 3  # primary + two private read replicas
    assert postgres.storage_size_mb == 2048
    assert postgres.app_database == "app"
    assert postgres.app_user == "rudder"
    assert not [value for name, value in api.calls if name == "workload"]
    aliases = [value for name, value in api.calls if name == "service"]
    assert [(alias.name, alias.external_name) for alias in aliases] == [
        ("postgres", "postgres-rw"),
        ("postgres-read", "postgres-ro"),
    ]
    assert result.pod_ids == {"postgres": "pod-postgres-1"}
    assert result.operation_observed["postgres"]["read_replicas"] == {
        "status": "configured",
        "replicas": 2,
        "endpoint": "postgres-read:5432",
    }


@pytest.mark.asyncio
async def test_rudder_managed_postgres_executes_one_physical_cnpg_backup() -> None:
    api = FakeKubernetesApi()
    runtime = KubernetesRuntime(
        api,
        RuntimeSettings(
            backup_s3_endpoint="http://minio:9000",
            backup_s3_bucket="rudder-backups",
            backup_s3_access_key="minio",
            backup_s3_secret_key="not-in-logs",
        ),
    )
    release = KubernetesRelease(
        namespace="rudder-shop-production",
        release_id="aabbccdd-1234-5678-9abc-def012345678",
        services=(
            ComposeService(
                name="postgres",
                image="postgres:16-alpine",
                port=5432,
                stateful=True,
                volume_mount_path="/var/lib/postgresql/data",
                managed_database_engine="postgres",
                environment={
                    "POSTGRES_DB": "app",
                    "POSTGRES_USER": "rudder",
                    "POSTGRES_PASSWORD": "not-in-logs",
                },
                operations={
                    "backups": {
                        "operation_id": "01234567-89ab-cdef-0123-456789abcdef",
                        "retention_days": 14,
                    }
                },
            ),
        ),
    )

    result = await runtime.apply(release, project_id="project", environment_id="environment")

    postgres = next(value for name, value in api.calls if name == "cloudnative-postgres")
    assert isinstance(postgres, CloudNativePostgresSpec)
    assert postgres.backup_retention_days == 14
    backup = next(value for name, value in api.calls if name == "cloudnative-postgres-backup")
    assert isinstance(backup, CloudNativePostgresBackupSpec)
    assert backup.cluster_name == "postgres"
    assert backup.retention_days == 14
    assert result.operation_observed["postgres"]["backup"] == {
        "status": "completed",
        "name": backup.name,
        "retention_days": 14,
    }


@pytest.mark.asyncio
async def test_stateful_members_keep_a_stable_identity_across_immutable_app_releases() -> None:
    """A web rollout must never recreate the database PVC under a new release name."""
    api = FakeKubernetesApi()
    runtime = KubernetesRuntime(api, RuntimeSettings(local_domain="localhost"))

    for release_id in ("aabbccdd-1111", "eeff0011-2222"):
        await runtime.apply(
            KubernetesRelease(
                namespace="rudder-shop-production",
                release_id=release_id,
                services=(
                    ComposeService(
                        name="postgres",
                        image="postgres:16-alpine",
                        port=5432,
                        stateful=True,
                        volume_mount_path="/var/lib/postgresql/data",
                    ),
                ),
            ),
            project_id="project",
            environment_id="environment",
        )

    workloads = [value for name, value in api.calls if name == "workload"]
    services = [value for name, value in api.calls if name == "service"]
    assert [workload.name for workload in workloads] == ["postgres", "postgres"]
    assert [service.name for service in services] == ["postgres", "postgres"]


@pytest.mark.asyncio
async def test_stateful_storage_intent_is_rendered_as_a_pvc_size() -> None:
    """Storage expansion changes the stateful volume target, not the app revision."""
    api = FakeKubernetesApi()
    runtime = KubernetesRuntime(api, RuntimeSettings())
    release = KubernetesRelease(
        namespace="rudder-shop-production",
        release_id="aabbccdd-1234-5678-9abc-def012345678",
        services=(
            ComposeService(
                name="postgres",
                image="postgres:16-alpine",
                port=5432,
                stateful=True,
                volume_mount_path="/var/lib/postgresql/data",
                operations={
                    "storage": {"current_size_mb": 1024, "requested_size_mb": 2048}
                },
            ),
        ),
    )

    await runtime.apply(release, project_id="project", environment_id="environment")

    workload = next(value for name, value in api.calls if name == "workload")
    assert workload.name == "postgres"
    assert workload.storage_size_mb == 2048
    assert next(value for name, value in api.calls if name == "storage") is workload


@pytest.mark.asyncio
async def test_runtime_uses_reviewed_public_domain_for_ingress() -> None:
    """The URL Rudder displays must be the hostname its ingress serves."""
    api = FakeKubernetesApi()
    runtime = KubernetesRuntime(api, RuntimeSettings(local_domain="localhost"))
    release = KubernetesRelease(
        namespace="rudder-shop-production",
        release_id="aabbccdd-1234-5678-9abc-def012345678",
        services=(
            ComposeService(
                name="web",
                image="registry/web@sha256:1",
                port=3000,
                public=True,
                public_host="shop.production.localhost",
            ),
        ),
    )

    result = await runtime.apply(release, project_id="project", environment_id="environment")

    ingress = next(value for name, value in api.calls if name == "ingress")
    assert ingress.host == "shop.production.localhost"
    assert result.public_hosts == {"web": "shop.production.localhost"}


@pytest.mark.asyncio
async def test_failed_candidate_is_cleaned_up_without_promoting_a_route() -> None:
    class UnreadyKubernetesApi(FakeKubernetesApi):
        async def wait_ready(
            self,
            namespace: str,
            spec: object,
            *,
            timeout_seconds: int,
            poll_seconds: float,
        ) -> str:
            self.calls.append(("ready", spec))
            raise RuntimeError("image pull failed")

    api = UnreadyKubernetesApi()
    runtime = KubernetesRuntime(api, RuntimeSettings(local_domain="localhost"))
    release = KubernetesRelease(
        namespace="rudder-shop-production",
        release_id="aabbccdd-1234-5678-9abc-def012345678",
        services=(
            ComposeService(name="web", image="registry/web@sha256:bad", port=3000, public=True),
        ),
    )

    with pytest.raises(RuntimeError, match="image pull failed"):
        await runtime.apply(release, project_id="project", environment_id="environment")

    assert not [value for name, value in api.calls if name == "ingress"]
    assert ("cleanup", ("rudder-shop-production", release.release_id)) in api.calls


@pytest.mark.asyncio
async def test_portless_worker_is_a_workload_without_an_invalid_service() -> None:
    api = FakeKubernetesApi()
    runtime = KubernetesRuntime(api, RuntimeSettings())
    release = KubernetesRelease(
        namespace="rudder-shop-production",
        release_id="aabbccdd-1234-5678-9abc-def012345678",
        services=(
            ComposeService(
                name="worker",
                image="registry/worker@sha256:1",
                command=("python", "worker.py"),
            ),
        ),
    )

    await runtime.apply(release, project_id="project", environment_id="environment")

    assert [name for name, _ in api.calls if name == "workload"] == ["workload"]
    assert not [name for name, _ in api.calls if name == "service"]


@pytest.mark.asyncio
async def test_runtime_renders_app_operations_as_workload_hpa_and_jobs() -> None:
    """Approved app intent becomes Kubernetes primitives without a source rebuild."""
    api = FakeKubernetesApi()
    runtime = KubernetesRuntime(api, RuntimeSettings())
    release = KubernetesRelease(
        namespace="rudder-shop-production",
        release_id="aabbccdd-1234-5678-9abc-def012345678",
        services=(
            ComposeService(
                name="worker",
                image="registry/worker@sha256:1",
                command=("python", "worker.py"),
                operations={
                    "replicas": 3,
                    "resources": {
                        "cpu_request": "400m",
                        "cpu_limit": "1",
                        "memory_request_mb": 384,
                        "memory_limit_mb": 768,
                    },
                    "autoscaling": {
                        "min_replicas": 2,
                        "max_replicas": 5,
                        "target_cpu_percent": 70,
                        "target_memory_percent": 80,
                    },
                    "placement": {
                        "node_selector": {"nodepool": "workers"},
                        "topology_spread": True,
                        "anti_affinity": True,
                        "max_unavailable": 1,
                    },
                    "rollout": {"strategy": "rolling"},
                    "observability": {"prometheus": True, "grafana": True},
                    "schedules": [
                        {
                            "operation_id": "schedule-1",
                            "spec": {
                                "cron": "*/5 * * * *",
                                "command": ["python", "cleanup.py"],
                                "timeout_seconds": 60,
                                "retries": 1,
                                "concurrency_policy": "forbid",
                            },
                        }
                    ],
                    "last_job": {
                        "command": ["python", "backfill.py"],
                        "timeout_seconds": 60,
                        "retries": 0,
                    },
                },
            ),
        ),
    )

    result = await runtime.apply(release, project_id="project", environment_id="environment")

    workload = next(value for name, value in api.calls if name == "workload")
    assert workload.replicas is None  # HPA owns replica count.
    assert workload.resources == {
        "requests": {"cpu": "400m", "memory": "384Mi"},
        "limits": {"cpu": "1", "memory": "768Mi"},
    }
    assert workload.node_selector == {"nodepool": "workers"}
    assert workload.anti_affinity is True
    assert workload.topology_spread is True
    assert workload.prometheus_enabled is True
    assert workload.rolling_update == {"max_surge": "25%", "max_unavailable": 0}
    disruption_budget = next(value for name, value in api.calls if name == "pdb")
    assert disruption_budget.max_unavailable == 1
    assert disruption_budget.workload_name == workload.name
    autoscaler = next(value for name, value in api.calls if name == "autoscaler")
    assert autoscaler.min_replicas == 2
    assert autoscaler.max_replicas == 5
    assert autoscaler.target_cpu_percent == 70
    assert autoscaler.target_memory_percent == 80
    assert [name for name, _ in api.calls if name == "cronjob"] == ["cronjob"]
    cron_job = next(value for name, value in api.calls if name == "cronjob")
    assert len(cron_job.name) <= 52
    assert [name for name, _ in api.calls if name == "job"] == ["job"]
    assert result.operation_observed["worker"]["observability"] == {
        "prometheus": "enabled",
        "grafana": "integration requested; no Grafana deployment is managed by Rudder",
    }


@pytest.mark.asyncio
async def test_runtime_prunes_disabled_hpa_and_cancelled_cronjobs_before_applying_intent() -> None:
    """Clearing runtime intent removes the owned primitive, rather than leaking it."""
    api = FakeKubernetesApi()
    runtime = KubernetesRuntime(api, RuntimeSettings())
    release = KubernetesRelease(
        namespace="rudder-shop-production",
        release_id="aabbccdd-1234-5678-9abc-def012345678",
        services=(ComposeService(name="worker", image="registry/worker@sha256:1"),),
    )

    result = await runtime.apply(release, project_id="project", environment_id="environment")

    assert ("delete-autoscaler", "worker-aabbccdd-hpa") in api.calls
    assert ("delete-cronjobs", ("worker-aabbccdd", release.release_id)) in api.calls
    assert result.operation_observed["worker"]["autoscaling"] == {"status": "disabled"}


@pytest.mark.asyncio
async def test_wait_ready_requires_the_requested_number_of_replicas() -> None:
    """One available pod is not sufficient for a three-replica release."""

    class Apps:
        async def read_namespaced_deployment_status(self, _name: str, _namespace: str):
            return SimpleNamespace(status=SimpleNamespace(available_replicas=1))

    api = object.__new__(AsyncKubernetesApi)
    api.apps = Apps()
    api.core = SimpleNamespace()
    spec = WorkloadSpec(
        name="web", service_name="web", image="registry/web@sha256:1", port=3000,
        command=None, environment={}, labels={}, stateful=False, volume_mount_path=None,
        replicas=3, ready_replicas=3,
    )

    with pytest.raises(RuntimeError, match="did not become ready"):
        await api.wait_ready("rudder", spec, timeout_seconds=0.003, poll_seconds=0.001)


@pytest.mark.asyncio
async def test_wait_ready_accepts_scale_to_zero_without_querying_pods() -> None:
    api = object.__new__(AsyncKubernetesApi)
    api.apps = SimpleNamespace()
    api.core = SimpleNamespace()
    spec = WorkloadSpec(
        name="worker", service_name="worker", image="registry/worker@sha256:1", port=None,
        command=None, environment={}, labels={}, stateful=False, volume_mount_path=None,
        replicas=0, ready_replicas=0,
    )

    assert await api.wait_ready("rudder", spec, timeout_seconds=1, poll_seconds=0.1) == "worker"


@pytest.mark.asyncio
async def test_cnpg_wait_accepts_ready_database_pod_when_operator_probe_is_unavailable() -> None:
    """Kind can block CNPG's TLS status probe even after PostgreSQL is ready.

    ``readyInstances`` is an operator-reported readiness count.  We additionally
    require the elected primary Pod's Kubernetes Ready condition before allowing
    the public application route to be promoted.
    """

    class Custom:
        async def get_namespaced_custom_object(self, **_kwargs):
            return {
                "status": {
                    "readyInstances": 1,
                    "currentPrimary": "postgres-1",
                    "conditions": [{"type": "Ready", "status": "False"}],
                }
            }

    class Core:
        async def read_namespaced_pod_status(self, name: str, namespace: str):
            assert (name, namespace) == ("postgres-1", "rudder")
            return SimpleNamespace(
                metadata=SimpleNamespace(uid="postgres-primary-uid"),
                status=SimpleNamespace(
                    conditions=[SimpleNamespace(type="Ready", status="True")]
                ),
            )

    api = object.__new__(AsyncKubernetesApi)
    api.custom = Custom()
    api.core = Core()
    spec = CloudNativePostgresSpec(
        name="postgres",
        service_name="postgres",
        app_database="app",
        app_user="rudder",
        app_password="secret",
        storage_size_mb=1024,
        instances=1,
        labels={},
    )

    assert await api.wait_cloudnative_postgres_ready(
        "rudder", spec, timeout_seconds=1, poll_seconds=0.1
    ) == "postgres-primary-uid"


@pytest.mark.asyncio
async def test_storage_expansion_patches_the_existing_stateful_pvc() -> None:
    """Expansion uses the existing PVC; it never rewrites the StatefulSet template."""

    class Core:
        def __init__(self) -> None:
            self.patch: tuple[str, str, object] | None = None

        async def read_namespaced_persistent_volume_claim(self, name: str, namespace: str):
            assert (name, namespace) == ("data-postgres-0", "rudder-shop")
            return SimpleNamespace(
                spec=SimpleNamespace(
                    storage_class_name="expandable",
                    resources=SimpleNamespace(requests={"storage": "1Gi"}),
                )
            )

        async def patch_namespaced_persistent_volume_claim(
            self, name: str, namespace: str, body: object
        ) -> None:
            self.patch = (name, namespace, body)

    class Storage:
        async def read_storage_class(self, name: str):
            assert name == "expandable"
            return SimpleNamespace(allow_volume_expansion=True)

    api = object.__new__(AsyncKubernetesApi)
    api.core = core = Core()
    api.storage = Storage()
    spec = WorkloadSpec(
        name="postgres", service_name="postgres", image="postgres:16", port=5432,
        command=None, environment={}, labels={}, stateful=True,
        volume_mount_path="/var/lib/postgresql/data", storage_size_mb=2048,
    )

    await api.expand_stateful_storage("rudder-shop", spec)

    assert core.patch is not None
    assert core.patch[0:2] == ("data-postgres-0", "rudder-shop")
    assert core.patch[2].spec.resources.requests == {"storage": "2048Mi"}


@pytest.mark.asyncio
async def test_storage_expansion_refuses_non_expandable_storage_class() -> None:
    class Core:
        async def read_namespaced_persistent_volume_claim(self, _name: str, _namespace: str):
            return SimpleNamespace(
                spec=SimpleNamespace(
                    storage_class_name="fixed",
                    resources=SimpleNamespace(requests={"storage": "1Gi"}),
                )
            )

    class Storage:
        async def read_storage_class(self, _name: str):
            return SimpleNamespace(allow_volume_expansion=False)

    api = object.__new__(AsyncKubernetesApi)
    api.core = Core()
    api.storage = Storage()
    spec = WorkloadSpec(
        name="postgres", service_name="postgres", image="postgres:16", port=5432,
        command=None, environment={}, labels={}, stateful=True,
        volume_mount_path="/var/lib/postgresql/data", storage_size_mb=2048,
    )

    with pytest.raises(RuntimeError, match="does not support volume expansion"):
        await api.expand_stateful_storage("rudder-shop", spec)


@pytest.mark.asyncio
async def test_existing_statefulset_keeps_its_immutable_claim_template() -> None:
    """Changing requested storage must not replace the immutable claim template."""

    class Apps:
        def __init__(self) -> None:
            self.replaced: object | None = None
            self.template = object()

        async def read_namespaced_stateful_set(self, name: str, namespace: str):
            assert (name, namespace) == ("postgres", "rudder-shop")
            return SimpleNamespace(
                metadata=SimpleNamespace(resource_version="42"),
                spec=SimpleNamespace(volume_claim_templates=[self.template]),
            )

        async def create_namespaced_stateful_set(self, *_args, **_kwargs) -> None:
            raise AssertionError("an existing StatefulSet must not be created")

        async def replace_namespaced_stateful_set(
            self, name: str, namespace: str, body: object
        ) -> None:
            assert (name, namespace) == ("postgres", "rudder-shop")
            self.replaced = body

    api = object.__new__(AsyncKubernetesApi)
    api.apps = apps = Apps()
    api.core = SimpleNamespace()
    spec = WorkloadSpec(
        name="postgres", service_name="postgres", image="postgres:16", port=5432,
        command=None, environment={}, labels={}, stateful=True,
        volume_mount_path="/var/lib/postgresql/data", storage_size_mb=2048,
    )

    await api.apply_workload("rudder-shop", spec)

    assert apps.replaced is not None
    assert apps.replaced.metadata.resource_version == "42"
    assert apps.replaced.spec.volume_claim_templates == [apps.template]


@pytest.mark.asyncio
async def test_runtime_marks_unsupported_progressive_rollouts_degraded() -> None:
    api = FakeKubernetesApi()
    runtime = KubernetesRuntime(api, RuntimeSettings())
    release = KubernetesRelease(
        namespace="rudder-shop-production",
        release_id="aabbccdd-1234-5678-9abc-def012345678",
        services=(
            ComposeService(
                name="web",
                image="registry/web@sha256:1",
                port=3000,
                operations={"rollout": {"strategy": "canary", "canary_steps": [10, 50, 100]}},
            ),
        ),
    )

    result = await runtime.apply(release, project_id="project", environment_id="environment")

    assert result.operation_observed["web"]["rollout"] == {
        "status": "degraded",
        "reason": "canary rollout requires a traffic manager and is not enabled for this cluster",
    }
