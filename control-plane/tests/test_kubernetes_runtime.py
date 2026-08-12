from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from kubernetes_asyncio.client import ApiException

from rudder_cp.runtime.kubernetes import (
    AsyncKubernetesApi,
    CloudNativePostgresBackupSpec,
    CloudNativePostgresScheduledBackupSpec,
    CloudNativePostgresSpec,
    JobSpec,
    KubernetesRuntime,
    RuntimeSettings,
    WorkloadSpec,
)
from rudder_cp.runtime.models import ComposeService, KubernetesRelease


class RecordingBackupIdentityBroker:
    """Test double for the separately-authorised GKE backup broker."""

    def __init__(self) -> None:
        self.bindings: list[tuple[str, str]] = []

    async def ensure_cnpg_binding(self, *, namespace: str, service_account_name: str) -> None:
        self.bindings.append((namespace, service_account_name))


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

    async def ensure_cnpg_backup_service_account(
        self, namespace: str, *, name: str, labels: dict[str, str]
    ) -> None:
        self.calls.append(("cnpg-backup-service-account", (namespace, name, labels)))

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

    async def apply_cloudnative_postgres_scheduled_backup(
        self, namespace: str, spec: object
    ) -> None:
        self.calls.append(("cloudnative-postgres-scheduled-backup", spec))

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
async def test_runtime_gke_placement_overrides_a_service_request_for_system_pool() -> None:
    """Customer release intent cannot place a Pod on the system pool."""

    api = FakeKubernetesApi()
    runtime = KubernetesRuntime(
        api,
        RuntimeSettings(
            workload_node_selector={"rudder.pool": "platform"},
            workload_tolerations=(
                {
                    "key": "rudder.pool",
                    "operator": "Equal",
                    "value": "platform",
                    "effect": "NoSchedule",
                },
            ),
        ),
    )
    release = KubernetesRelease(
        namespace="rudder-shop-production",
        release_id="aabbccdd-1234-5678-9abc-def012345678",
        services=(
            ComposeService(
                name="web",
                image="registry/web@sha256:1",
                port=3000,
                operations={"placement": {"node_selector": {"rudder.pool": "system"}}},
            ),
        ),
    )

    await runtime.apply(release, project_id="project", environment_id="environment")

    workload = next(value for name, value in api.calls if name == "workload")
    assert workload.node_selector == {"rudder.pool": "platform"}
    assert workload.tolerations == (
        {
            "key": "rudder.pool",
            "operator": "Equal",
            "value": "platform",
            "effect": "NoSchedule",
        },
    )


@pytest.mark.asyncio
async def test_workload_template_renders_the_platform_toleration() -> None:
    """The Kubernetes Pod template must tolerate the platform NoSchedule taint."""

    class Apps:
        read_namespaced_deployment = object()
        create_namespaced_deployment = object()
        replace_namespaced_deployment = object()

    api = object.__new__(AsyncKubernetesApi)
    api.apps = Apps()
    api.core = SimpleNamespace()
    rendered: list[object] = []

    async def create_or_replace(*args, **_kwargs) -> None:
        rendered.append(args[4])

    api._create_or_replace = create_or_replace
    spec = WorkloadSpec(
        name="web",
        service_name="web",
        image="registry/web@sha256:1",
        port=3000,
        command=None,
        environment={},
        labels={},
        stateful=False,
        volume_mount_path=None,
        node_selector={"rudder.pool": "platform"},
        tolerations=(
            {
                "key": "rudder.pool",
                "operator": "Equal",
                "value": "platform",
                "effect": "NoSchedule",
            },
        ),
    )

    await api.apply_workload("rudder-shop", spec)

    pod_spec = rendered[0].spec.template.spec
    assert pod_spec.node_selector == {"rudder.pool": "platform"}
    assert len(pod_spec.tolerations) == 1
    assert pod_spec.tolerations[0].to_dict() == {
        "effect": "NoSchedule",
        "key": "rudder.pool",
        "operator": "Equal",
        "toleration_seconds": None,
        "value": "platform",
    }


@pytest.mark.asyncio
async def test_guardrails_default_deny_egress_except_dns_and_same_environment() -> None:
    """An environment may only talk to its own services plus cluster DNS.

    A namespace-scoped ingress policy alone does not stop a compromised Pod
    from initiating traffic to another namespace or the public internet.  The
    generated guardrail must therefore select both Ingress and Egress and keep
    its only egress exceptions deliberately small.
    """

    api = object.__new__(AsyncKubernetesApi)
    api.settings = RuntimeSettings()
    api.core = SimpleNamespace(
        read_namespaced_resource_quota=object(),
        create_namespaced_resource_quota=object(),
        replace_namespaced_resource_quota=object(),
        read_namespaced_limit_range=object(),
        create_namespaced_limit_range=object(),
        replace_namespaced_limit_range=object(),
    )
    api.networking = SimpleNamespace(
        read_namespaced_network_policy=object(),
        create_namespaced_network_policy=object(),
        replace_namespaced_network_policy=object(),
    )
    rendered: dict[str, object] = {}

    async def create_or_replace(_read, _create, _replace, name, body, *, namespace) -> None:
        assert namespace == "rudder-shop"
        rendered[name] = body

    api._create_or_replace = create_or_replace

    await api.ensure_guardrails("rudder-shop", {"rudder.environment": "environment-id"})

    policy = rendered["rudder-private-network"]
    assert policy.spec.policy_types == ["Ingress", "Egress"]
    assert policy.spec.egress is not None

    same_environment = policy.spec.egress[0].to[0]
    assert same_environment.namespace_selector.match_labels == {
        "rudder.environment": "environment-id"
    }

    dns = policy.spec.egress[1]
    assert dns.to[0].namespace_selector.match_labels == {
        "kubernetes.io/metadata.name": "kube-system"
    }
    assert {(port.protocol, port.port) for port in dns.ports} == {("TCP", 53), ("UDP", 53)}
    assert all(rule.to for rule in policy.spec.egress)

    cnpg_status = policy.spec.ingress[1]
    assert cnpg_status._from[0].namespace_selector.match_labels == {
        "kubernetes.io/metadata.name": "cnpg-system"
    }
    assert cnpg_status._from[0].pod_selector.match_labels == {
        "app.kubernetes.io/name": "cloudnative-pg"
    }
    assert [(port.protocol, port.port) for port in cnpg_status.ports] == [("TCP", 8000)]


@pytest.mark.asyncio
async def test_guardrails_allow_only_configured_kubernetes_api_service() -> None:
    api = object.__new__(AsyncKubernetesApi)
    api.settings = RuntimeSettings(kubernetes_api_server_endpoint_cidr="10.80.0.15/32")
    api.core = SimpleNamespace(
        read_namespaced_resource_quota=object(),
        create_namespaced_resource_quota=object(),
        replace_namespaced_resource_quota=object(),
        read_namespaced_limit_range=object(),
        create_namespaced_limit_range=object(),
        replace_namespaced_limit_range=object(),
    )
    api.networking = SimpleNamespace(
        read_namespaced_network_policy=object(),
        create_namespaced_network_policy=object(),
        replace_namespaced_network_policy=object(),
    )
    rendered: dict[str, object] = {}

    async def create_or_replace(_read, _create, _replace, name, body, *, namespace) -> None:
        rendered[name] = body

    api._create_or_replace = create_or_replace

    await api.ensure_guardrails("rudder-shop", {"rudder.environment": "environment-id"})

    api_egress = rendered["rudder-private-network"].spec.egress[2]
    assert api_egress.to[0].ip_block.cidr == "10.80.0.15/32"
    assert [(port.protocol, port.port) for port in api_egress.ports] == [("TCP", 443)]


@pytest.mark.asyncio
async def test_failed_candidate_cleanup_never_deletes_persistent_volume_claims() -> None:
    """Normal release cleanup must preserve state, including failed releases."""
    api = object.__new__(AsyncKubernetesApi)
    api.apps = SimpleNamespace(
        delete_collection_namespaced_deployment=AsyncMock(),
        delete_collection_namespaced_stateful_set=AsyncMock(),
    )
    api.autoscaling = SimpleNamespace(
        delete_collection_namespaced_horizontal_pod_autoscaler=AsyncMock()
    )
    api.policy = SimpleNamespace(delete_collection_namespaced_pod_disruption_budget=AsyncMock())
    api.batch = SimpleNamespace(
        delete_collection_namespaced_job=AsyncMock(),
        delete_collection_namespaced_cron_job=AsyncMock(),
    )
    api.core = SimpleNamespace(
        delete_collection_namespaced_service=AsyncMock(),
        delete_collection_namespaced_secret=AsyncMock(),
        # The assertion is intentionally made on the mock itself rather than
        # relying on absent attributes: this guards against a future cleanup
        # implementation reintroducing PVC deletion.
        delete_collection_namespaced_persistent_volume_claim=AsyncMock(),
    )

    await api.delete_release("rudder-shop-production", "candidate-release")

    api.core.delete_collection_namespaced_persistent_volume_claim.assert_not_awaited()


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
async def test_runtime_gke_placement_also_applies_to_managed_postgres_and_jobs() -> None:
    """All generated customer Pod types must tolerate the shared pool taint."""

    placement = {"rudder.pool": "platform"}
    tolerations = (
        {
            "key": "rudder.pool",
            "operator": "Equal",
            "value": "platform",
            "effect": "NoSchedule",
        },
    )
    api = FakeKubernetesApi()
    runtime = KubernetesRuntime(
        api,
        RuntimeSettings(workload_node_selector=placement, workload_tolerations=tolerations),
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
                environment={"POSTGRES_PASSWORD": "not-in-logs"},
            ),
            ComposeService(
                name="worker",
                image="registry/worker@sha256:1",
                operations={
                    "schedules": [
                        {
                            "operation_id": "daily",
                            "spec": {"cron": "0 0 * * *", "command": ["python", "daily.py"]},
                        }
                    ],
                    "last_job": {"command": ["python", "once.py"]},
                },
            ),
        ),
    )

    await runtime.apply(release, project_id="project", environment_id="environment")

    postgres = next(value for name, value in api.calls if name == "cloudnative-postgres")
    cron_job = next(value for name, value in api.calls if name == "cronjob")
    job = next(value for name, value in api.calls if name == "job")
    for spec in (postgres, cron_job, job):
        assert spec.node_selector == placement
        assert spec.tolerations == tolerations


def test_job_template_renders_the_platform_toleration() -> None:
    """CronJob and Job Pod templates receive the same taint toleration."""

    api = object.__new__(AsyncKubernetesApi)
    toleration = {
        "key": "rudder.pool",
        "operator": "Equal",
        "value": "platform",
        "effect": "NoSchedule",
    }
    template = api._job_template(
        JobSpec(
            name="worker-job",
            image="registry/worker@sha256:1",
            command=("python", "worker.py"),
            environment={},
            labels={},
            timeout_seconds=60,
            retries=0,
            node_selector={"rudder.pool": "platform"},
            tolerations=(toleration,),
        )
    )

    assert template.spec.node_selector == {"rudder.pool": "platform"}
    assert template.spec.tolerations[0].to_dict()["effect"] == "NoSchedule"


@pytest.mark.asyncio
async def test_cnpg_template_renders_the_platform_placement() -> None:
    """Managed PostgreSQL Pods receive the shared-pool affinity contract."""

    class Core:
        async def read_namespaced_secret(self, **_kwargs):
            raise ApiException(status=404)

        async def create_namespaced_secret(self, **_kwargs) -> None:
            return None

        async def replace_namespaced_secret(self, **_kwargs) -> None:
            raise AssertionError("a new Secret should be created")

    class Custom:
        def __init__(self) -> None:
            self.body: dict[str, object] | None = None

        async def get_namespaced_custom_object(self, **_kwargs):
            raise ApiException(status=404)

        async def create_namespaced_custom_object(self, **kwargs) -> None:
            self.body = kwargs["body"]

        async def replace_namespaced_custom_object(self, **_kwargs) -> None:
            raise AssertionError("a new cluster should be created")

    api = object.__new__(AsyncKubernetesApi)
    api.settings = RuntimeSettings()
    api.core = Core()
    api.custom = custom = Custom()
    await api.apply_cloudnative_postgres(
        "rudder-shop",
        CloudNativePostgresSpec(
            name="postgres",
            service_name="postgres",
            app_database="app",
            app_user="rudder",
            app_password="not-in-logs",
            storage_size_mb=1024,
            instances=1,
            labels={},
            node_selector={"rudder.pool": "platform"},
            tolerations=(
                {
                    "key": "rudder.pool",
                    "operator": "Equal",
                    "value": "platform",
                    "effect": "NoSchedule",
                },
            ),
        ),
    )

    assert custom.body is not None
    affinity = custom.body["spec"]["affinity"]
    assert affinity == {
        "nodeSelector": {"rudder.pool": "platform"},
        "tolerations": [
            {
                "key": "rudder.pool",
                "operator": "Equal",
                "value": "platform",
                "effect": "NoSchedule",
            }
        ],
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
async def test_rudder_managed_postgres_creates_a_durable_cnpg_backup_schedule() -> None:
    api = FakeKubernetesApi()
    runtime = KubernetesRuntime(
        api,
        RuntimeSettings(
            backup_s3_endpoint="http://minio:9000",
            backup_s3_bucket="rudder-backups",
            backup_s3_access_key="minio",
            backup_s3_secret_key="not-in-logs",
            backup_schedule="0 0 2 * * *",
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
            ),
        ),
    )

    result = await runtime.apply(release, project_id="project", environment_id="environment")

    postgres = next(value for name, value in api.calls if name == "cloudnative-postgres")
    assert isinstance(postgres, CloudNativePostgresSpec)
    assert postgres.backup_retention_days == 7
    scheduled = next(
        value for name, value in api.calls if name == "cloudnative-postgres-scheduled-backup"
    )
    assert isinstance(scheduled, CloudNativePostgresScheduledBackupSpec)
    assert scheduled.name == "postgres-scheduled-backup"
    assert scheduled.cluster_name == "postgres"
    assert scheduled.schedule == "0 0 2 * * *"
    assert result.operation_observed["postgres"]["scheduled_backup"] == {
        "status": "configured",
        "name": "postgres-scheduled-backup",
        "schedule": "0 0 2 * * *",
    }


@pytest.mark.asyncio
async def test_gke_cnpg_backup_binds_only_its_environment_service_account() -> None:
    """A GCS-enabled CNPG release cannot skip its per-environment identity binding."""

    api = FakeKubernetesApi()
    broker = RecordingBackupIdentityBroker()
    runtime = KubernetesRuntime(
        api,
        RuntimeSettings(
            backup_gcs_bucket="rudder-backups",
            backup_gcp_service_account="rudder-backup@example.iam.gserviceaccount.com",
        ),
        backup_identity_broker=broker,
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
            ),
        ),
    )

    await runtime.apply(release, project_id="project", environment_id="environment")

    assert broker.bindings == [("rudder-shop-production", "postgres")]
    names = [name for name, _value in api.calls]
    assert names.index("cnpg-backup-service-account") < names.index("cloudnative-postgres")
    assert names.index("cloudnative-postgres") > names.index("guardrails")


@pytest.mark.asyncio
async def test_cnpg_gke_backup_uses_workload_identity_without_a_credential_secret() -> None:
    """GKE backups use CNPG's native identity mode, never a static key Secret."""

    class Core:
        def __init__(self) -> None:
            self.created: list[object] = []

        async def read_namespaced_secret(self, **_kwargs):
            raise ApiException(status=404)

        async def create_namespaced_secret(self, *, namespace: str, body: object) -> None:
            assert namespace == "rudder-shop-production"
            self.created.append(body)

        async def replace_namespaced_secret(self, **_kwargs) -> None:
            raise AssertionError("no existing Secret is expected")

    class Custom:
        def __init__(self) -> None:
            self.created: object | None = None

        async def get_namespaced_custom_object(self, **_kwargs):
            raise ApiException(status=404)

        async def create_namespaced_custom_object(self, **kwargs) -> None:
            self.created = kwargs["body"]

        async def replace_namespaced_custom_object(self, **_kwargs) -> None:
            raise AssertionError("no existing CNPG cluster is expected")

    api = object.__new__(AsyncKubernetesApi)
    api.settings = RuntimeSettings(
        backup_gcs_bucket="rudder-backups",
        backup_gcp_service_account="rudder-backup@example.iam.gserviceaccount.com",
    )
    api.networking = SimpleNamespace(
        read_namespaced_network_policy=object(),
        create_namespaced_network_policy=object(),
        replace_namespaced_network_policy=object(),
    )
    rendered_network_policies: dict[str, object] = {}

    original_create_or_replace = api._create_or_replace

    async def create_or_replace(read, create, replace, name, body, *, namespace) -> None:
        assert namespace == "rudder-shop-production"
        if name == "postgres-backup-egress":
            rendered_network_policies[name] = body
            return
        await original_create_or_replace(read, create, replace, name, body, namespace=namespace)

    api._create_or_replace = create_or_replace
    api.core = core = Core()
    api.custom = custom = Custom()
    spec = CloudNativePostgresSpec(
        name="postgres",
        service_name="postgres",
        app_database="app",
        app_user="rudder",
        app_password="not-in-logs",
        storage_size_mb=1024,
        instances=1,
        labels={"rudder.service": "postgres"},
        backup_retention_days=14,
    )

    await api.apply_cloudnative_postgres("rudder-shop-production", spec)

    assert len(core.created) == 1  # only the application-user Secret
    assert isinstance(custom.created, dict)
    rendered = custom.created["spec"]
    assert rendered["backup"] == {
        "retentionPolicy": "14d",
        "barmanObjectStore": {
            "destinationPath": "gs://rudder-backups/rudder/rudder-shop-production/postgres",
            "googleCredentials": {"gkeEnvironment": True},
            "wal": {"compression": "gzip"},
        },
    }
    assert rendered["serviceAccountTemplate"] == {
        "metadata": {
            "annotations": {
                "iam.gke.io/gcp-service-account": "rudder-backup@example.iam.gserviceaccount.com"
            }
        }
    }
    backup_egress = rendered_network_policies["postgres-backup-egress"]
    assert backup_egress.spec.pod_selector.match_labels == {"cnpg.io/cluster": "postgres"}
    assert backup_egress.spec.policy_types == ["Egress"]
    assert [(port.protocol, port.port) for port in backup_egress.spec.egress[0].ports] == [
        ("TCP", 53),
        ("UDP", 53),
    ]
    assert backup_egress.spec.egress[0].to is None
    assert backup_egress.spec.egress[2].to is None
    assert [(port.protocol, port.port) for port in backup_egress.spec.egress[2].ports] == [
        ("TCP", 443)
    ]


@pytest.mark.asyncio
async def test_cnpg_scheduled_backup_uses_the_operator_cron_contract() -> None:
    class Custom:
        def __init__(self) -> None:
            self.created: object | None = None

        async def get_namespaced_custom_object(self, **_kwargs):
            raise ApiException(status=404)

        async def create_namespaced_custom_object(self, **kwargs) -> None:
            self.created = kwargs

    api = object.__new__(AsyncKubernetesApi)
    api.custom = custom = Custom()
    spec = CloudNativePostgresScheduledBackupSpec(
        name="postgres-scheduled-backup",
        cluster_name="postgres",
        schedule="0 0 2 * * *",
        labels={"rudder.service": "postgres"},
    )

    await api.apply_cloudnative_postgres_scheduled_backup("rudder-shop-production", spec)

    assert custom.created == {
        "group": "postgresql.cnpg.io",
        "version": "v1",
        "namespace": "rudder-shop-production",
        "plural": "scheduledbackups",
        "body": {
            "apiVersion": "postgresql.cnpg.io/v1",
            "kind": "ScheduledBackup",
            "metadata": {
                "name": "postgres-scheduled-backup",
                "labels": {"rudder.service": "postgres"},
            },
            "spec": {
                "schedule": "0 0 2 * * *",
                "backupOwnerReference": "self",
                "cluster": {"name": "postgres"},
                "method": "barmanObjectStore",
            },
        },
    }


async def test_cnpg_does_not_attach_unverified_gke_backup_identity() -> None:
    """An operator must explicitly mark the KSA↔GSA binding ready first."""

    class Core:
        async def read_namespaced_secret(self, **_kwargs):
            raise ApiException(status=404)

        async def create_namespaced_secret(self, **_kwargs) -> None:
            return None

        async def replace_namespaced_secret(self, **_kwargs) -> None:
            raise AssertionError("no existing Secret is expected")

    class Custom:
        def __init__(self) -> None:
            self.created: object | None = None

        async def get_namespaced_custom_object(self, **_kwargs):
            raise ApiException(status=404)

        async def create_namespaced_custom_object(self, **kwargs) -> None:
            self.created = kwargs["body"]

        async def replace_namespaced_custom_object(self, **_kwargs) -> None:
            raise AssertionError("no existing CNPG cluster is expected")

    api = object.__new__(AsyncKubernetesApi)
    # A raw GCS account value must not make it into a release until the
    # platform marks its exact Workload Identity binding ready.
    api.settings = RuntimeSettings()
    api.core = Core()
    api.custom = custom = Custom()
    spec = CloudNativePostgresSpec(
        name="postgres",
        service_name="postgres",
        app_database="app",
        app_user="rudder",
        app_password="not-in-logs",
        storage_size_mb=1024,
        instances=1,
        labels={"rudder.service": "postgres"},
        backup_retention_days=14,
    )

    await api.apply_cloudnative_postgres("rudder-shop-production", spec)

    assert isinstance(custom.created, dict)
    assert "backup" not in custom.created["spec"]
    assert "serviceAccountTemplate" not in custom.created["spec"]


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
async def test_runtime_uses_a_stable_cert_manager_secret_for_a_public_route() -> None:
    """A production route must request HTTPS without changing its URL per release."""
    api = FakeKubernetesApi()
    runtime = KubernetesRuntime(
        api,
        RuntimeSettings(
            local_domain="rudder.invytt.com",
            certificate_issuer="rudder-letsencrypt-prod",
        ),
    )
    release = KubernetesRelease(
        namespace="rudder-shop-production",
        release_id="aabbccdd-1234-5678-9abc-def012345678",
        services=(
            ComposeService(
                name="web",
                image="registry/web@sha256:1",
                port=3000,
                public=True,
                public_host="shop.production.rudder.invytt.com",
            ),
        ),
    )

    await runtime.apply(release, project_id="project", environment_id="environment")

    ingress = next(value for name, value in api.calls if name == "ingress")
    assert ingress.tls_secret_name == "route-web-tls"
    assert ingress.certificate_issuer == "rudder-letsencrypt-prod"


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
