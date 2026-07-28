"""End-to-end check for the Phase 3 local Kubernetes runtime.

This deliberately enters through ``run_deployment`` with the same persisted
project/environment/GitHub-import graph used by the product.  The good release
uses a recorded immutable nginx image so the acceptance check never needs a
GitHub checkout or a network build; unit tests cover the BuildKit call itself.
The broken candidate proves readiness-gated promotion preserves the old route.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
import time
import uuid
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from kubernetes_asyncio import client
from kubernetes_asyncio.client import ApiException
from sqlmodel import Session, SQLModel, create_engine, select

from rudder_cp.config import Settings
from rudder_cp.logs.store import BuildLogStore
from rudder_cp.models import (
    Deployment,
    DeploymentStatus,
    Domain,
    Environment,
    GitHubImport,
    GitHubImportService,
    Instance,
    Node,
    NodeStatus,
    Project,
    Service,
    User,
    Volume,
)
from rudder_cp.runtime.kubernetes import AsyncKubernetesApi, RuntimeSettings
from rudder_cp.runtime.models import dns_label
from rudder_cp.services.deploy import run_deployment


async def main() -> None:
    suffix = uuid.uuid4().hex[:8]
    with tempfile.TemporaryDirectory(prefix="rudder-kind-e2e-") as temporary_directory:
        await _verify_imported_release(Path(temporary_directory), suffix)


async def _verify_imported_release(temp_dir: Path, suffix: str) -> None:
    settings = Settings(
        runtime="kubernetes",
        kubernetes_kubeconfig=os.environ.get("RUDDER_KUBERNETES_KUBECONFIG", ""),
        kubernetes_local_domain="localhost",
        kubernetes_readiness_timeout_seconds=180,
        build_log_dir=str(temp_dir / "logs"),
        secret_keys="",
    )
    engine = create_engine(f"sqlite:///{temp_dir / 'metadata.db'}")
    SQLModel.metadata.create_all(engine)
    release = _create_imported_release(engine, suffix)
    namespace = release.namespace
    deployment_id = release.deployment_id
    host = release.host
    api_settings = RuntimeSettings(local_domain=settings.kubernetes_local_domain)
    api = await AsyncKubernetesApi.from_kubeconfig(
        api_settings,
        kubeconfig_path=settings.kubernetes_kubeconfig,
    )
    try:
        store = BuildLogStore(settings.build_log_dir)
        with Session(engine) as session:
            outcome = await run_deployment(
                deployment_id,
                session=session,
                engine=engine,
                agent=object(),  # The Kubernetes path never contacts a Docker agent.
                store=store,
                settings=settings,
                builder=_builder_must_not_run,
            )
        if outcome.status is not DeploymentStatus.LIVE:
            raise RuntimeError(outcome.detail or "imported Kubernetes release did not go live")
        with Session(engine) as session:
            instances = list(
                session.exec(
                    select(Instance).where(Instance.deployment_id == deployment_id)
                ).all()
            )
            if {instance.compose_service for instance in instances} != {
                "web",
                "worker",
                "postgres",
                "redis",
            }:
                raise RuntimeError("imported Kubernetes release did not record every workload")
        await _wait_for_ingress(host)
        await _assert_private_services_have_no_ingress(api, namespace)
        await _assert_failed_candidate_preserves_live_route(
            engine, settings, store, api, namespace, host, release.service_id
        )
        print(f"kind end-to-end verification passed: http://{host}")
    finally:
        await api.core.delete_namespace(
            namespace,
            body=client.V1DeleteOptions(propagation_policy="Background"),
        )
        await _wait_for_namespace_deletion(api, namespace)
        await api.close()
        SQLModel.metadata.drop_all(engine)
        engine.dispose()


class ImportedRelease:
    def __init__(self, namespace: str, host: str, deployment_id: uuid.UUID, service_id: uuid.UUID):
        self.namespace = namespace
        self.host = host
        self.deployment_id = deployment_id
        self.service_id = service_id


def _create_imported_release(engine, suffix: str) -> ImportedRelease:
    """Persist a real GitHub import topology without external GitHub state."""
    with Session(engine) as session:
        user = User(email=f"kind-{suffix}@example.test", password_hash="not-used")
        session.add(user)
        session.commit()
        project = Project(name=f"kind-e2e-{suffix}", owner_id=user.id)
        session.add(project)
        session.commit()
        environment = Environment(project_id=project.id, name="production", is_production=True)
        anchor = Node(
            hostname=f"kind-anchor-{suffix}",
            ip_address="127.0.0.1",
            status=NodeStatus.HEALTHY,
            cpu_total=4,
            memory_total_mb=8192,
        )
        session.add_all([environment, anchor])
        session.commit()
        web = Service(
            environment_id=environment.id,
            name="web",
            source_repo="local/kind-e2e",
            container_port=80,
            build_config={"compose_service": "web"},
        )
        worker = Service(
            environment_id=environment.id,
            name="worker",
            container_port=0,
            build_config={"compose_service": "worker"},
        )
        postgres = Service(
            environment_id=environment.id,
            name="postgres",
            container_port=5432,
            build_config={"compose_service": "postgres"},
        )
        redis = Service(
            environment_id=environment.id,
            name="redis",
            container_port=6379,
            build_config={"compose_service": "redis"},
        )
        session.add_all([web, worker, postgres, redis])
        session.commit()
        session.add(
            Domain(
                hostname="web.production.localhost",
                environment_id=environment.id,
                service_id=web.id,
                is_system=True,
            )
        )
        session.commit()
        session.add_all(
            [
                Volume(service_id=postgres.id, mount_path="/var/lib/postgresql/data"),
                Volume(service_id=redis.id, mount_path="/data"),
            ]
        )
        imported = GitHubImport(
            installation_id=0,
            repository="local/kind-e2e",
            branch="main",
            compose_source="generated",
            compose_project_name=f"rudder-kind-e2e-{suffix}",
            compose_manifest=(
                "services:\n"
                "  web:\n    image: nginx:1.27-alpine\n    expose: ['80']\n"
                "  worker:\n    image: busybox:1.36\n"
                "    command: ['/bin/sh', '-c', 'while true; do sleep 3600; done']\n"
                "  postgres:\n    image: postgres:16-alpine\n    expose: ['5432']\n"
                "    environment:\n      POSTGRES_PASSWORD: rudder\n"
                "  redis:\n    image: redis:7-alpine\n    expose: ['6379']\n"
            ),
            project_id=project.id,
            app_service_id=web.id,
            postgres_service_id=postgres.id,
            redis_service_id=redis.id,
        )
        session.add(imported)
        session.commit()
        session.add_all(
            [
                GitHubImportService(
                    github_import_id=imported.id,
                    service_id=web.id,
                    compose_service="web",
                    role="web",
                    is_public=True,
                ),
                GitHubImportService(
                    github_import_id=imported.id,
                    service_id=worker.id,
                    compose_service="worker",
                    role="worker",
                ),
                GitHubImportService(
                    github_import_id=imported.id,
                    service_id=postgres.id,
                    compose_service="postgres",
                    role="database",
                ),
                GitHubImportService(
                    github_import_id=imported.id,
                    service_id=redis.id,
                    compose_service="redis",
                    role="cache",
                ),
            ]
        )
        deployment = Deployment(
            service_id=web.id,
            image_tag="nginx:1.27-alpine",
            commit_sha="kind-e2e",
            status=DeploymentStatus.QUEUED,
        )
        session.add(deployment)
        session.commit()
        namespace = dns_label(f"rudder-{environment.id.hex[:12]}")
        return ImportedRelease(
            namespace,
            "web.production.localhost",
            deployment.id,
            web.id,
        )


async def _builder_must_not_run(*_args, **_kwargs):
    raise AssertionError("the recorded immutable image must bypass the builder")


async def _wait_for_ingress(host: str) -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            if await asyncio.to_thread(_request_status, host) == 200:
                return
        except (URLError, TimeoutError):
            pass
        await asyncio.sleep(2)
    raise RuntimeError(f"public ingress did not route {host} through localhost:8081")


async def _assert_private_services_have_no_ingress(api: AsyncKubernetesApi, namespace: str) -> None:
    ingresses = await api.networking.list_namespaced_ingress(namespace)
    hosts = {
        rule.host
        for ingress in ingresses.items
        for rule in (ingress.spec.rules or [])
        if rule.host
    }
    if hosts != {"web.production.localhost"}:
        raise RuntimeError(
            f"private services unexpectedly received ingress routes: {sorted(hosts)}"
        )


async def _assert_failed_candidate_preserves_live_route(
    engine, settings: Settings, store: BuildLogStore, api: AsyncKubernetesApi, namespace: str,
    host: str, service_id: uuid.UUID,
) -> None:
    """A broken candidate must not replace the prior ready ingress backend."""
    candidate_id: uuid.UUID
    with Session(engine) as session:
        candidate = Deployment(
            service_id=service_id,
            image_tag="localhost:5000/rudder-does-not-exist:never",
            commit_sha="broken",
            status=DeploymentStatus.QUEUED,
        )
        session.add(candidate)
        session.commit()
        candidate_id = candidate.id
    short_settings = settings.model_copy(update={"kubernetes_readiness_timeout_seconds": 12})
    with Session(engine) as session:
        outcome = await run_deployment(
            candidate_id,
            session=session,
            engine=engine,
            agent=object(),
            store=store,
            settings=short_settings,
            builder=_builder_must_not_run,
        )
    if outcome.status is not DeploymentStatus.FAILED:
        raise RuntimeError("known-broken Kubernetes candidate unexpectedly became ready")

    if await asyncio.to_thread(_request_status, host) != 200:
        raise RuntimeError("broken candidate disrupted the prior public route")
    try:
        await api.apps.read_namespaced_deployment_status(f"web-{str(candidate_id)[:8]}", namespace)
    except ApiException as exc:
        if exc.status == 404:
            return
        raise
    raise RuntimeError("failed candidate workload was not cleaned up")


async def _wait_for_namespace_deletion(api: AsyncKubernetesApi, namespace: str) -> None:
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            await api.core.read_namespace(namespace)
        except ApiException as exc:
            if exc.status == 404:
                return
            raise
        await asyncio.sleep(1)
    raise RuntimeError(f"temporary Kind namespace {namespace} was not deleted")


def _request_status(host: str) -> int:
    request = Request("http://127.0.0.1/", headers={"Host": host})
    with urlopen(request, timeout=2) as response:
        return response.status


if __name__ == "__main__":
    asyncio.run(main())
