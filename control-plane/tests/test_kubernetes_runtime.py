import pytest

from rudder_cp.runtime.kubernetes import KubernetesRuntime, RuntimeSettings
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
    assert [workload.name for workload in workloads] == ["web-aabbccdd", "postgres-aabbccdd"]
    assert workloads[0].stateful is False
    assert workloads[1].stateful is True
    assert workloads[1].volume_mount_path == "/var/lib/postgresql/data"
    assert [name for name, _ in api.calls].index("ingress") > [name for name, _ in api.calls].index(
        "ready"
    )
    assert result.pod_ids == {"web": "pod-web-aabbccdd", "postgres": "pod-postgres-aabbccdd"}
    assert result.public_hosts == {"web": "web-rudder-shop-production.localhost"}


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
