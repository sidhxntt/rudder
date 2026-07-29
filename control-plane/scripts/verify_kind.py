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
    OperationKind,
    OperationStatus,
    Project,
    Service,
    ServiceManagedCapabilities,
    ServiceOperation,
    ServiceOperationsState,
    User,
    Volume,
)
from rudder_cp.runtime.kubernetes import AsyncKubernetesApi, RuntimeSettings
from rudder_cp.runtime.models import dns_label
from rudder_cp.services.deploy import run_deployment
from rudder_cp.services.operation_dispatch import reconcile_pending_rollbacks


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
        app_controls_deployment_id = await _assert_app_workload_controls(
            engine, settings, store, api, release
        )
        await _assert_autoscaling_and_jobs(engine, settings, store, api, release)
        await _assert_managed_postgres_controls(engine, settings, store, api, release)
        await _assert_immutable_kubernetes_restore(
            engine,
            settings,
            api,
            release,
            target_deployment_id=app_controls_deployment_id,
        )
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
    def __init__(
        self,
        namespace: str,
        host: str,
        deployment_id: uuid.UUID,
        service_id: uuid.UUID,
        postgres_service_id: uuid.UUID,
    ):
        self.namespace = namespace
        self.host = host
        self.deployment_id = deployment_id
        self.service_id = service_id
        self.postgres_service_id = postgres_service_id


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
        session.add(
            ServiceManagedCapabilities(
                service_id=postgres.id,
                database_engine="postgres",
                data_role="primary",
                source="catalog",
            )
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
            postgres.id,
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


async def _assert_app_workload_controls(
    engine,
    settings: Settings,
    store: BuildLogStore,
    api: AsyncKubernetesApi,
    release: ImportedRelease,
) -> uuid.UUID:
    """Exercise the manual application controls exposed by the dashboard.

    This is an immutable-image deployment: changing the app's size/resources
    must render a new Kubernetes candidate, retain the public URL, and never
    invoke a source build.
    """
    desired = {
        "replicas": 2,
        "resources": {
            "cpu_request": "200m",
            "cpu_limit": "500m",
            "memory_request_mb": 128,
            "memory_limit_mb": 256,
        },
        "placement": {
            "anti_affinity": True,
            "topology_spread": True,
            "max_unavailable": 1,
        },
        "rollout": {"strategy": "rolling"},
        "observability": {"prometheus": True, "grafana": True},
    }
    with Session(engine) as session:
        session.add(
            ServiceOperationsState(
                service_id=release.service_id,
                desired=desired,
                pending_reconciliation=True,
                version=1,
            )
        )
        session.add_all(
            [
                ServiceOperation(
                    service_id=release.service_id,
                    kind=OperationKind.SCALE,
                    requested={"replicas": 2},
                ),
                ServiceOperation(
                    service_id=release.service_id,
                    kind=OperationKind.RESOURCES,
                    requested=desired["resources"],
                ),
                ServiceOperation(
                    service_id=release.service_id,
                    kind=OperationKind.PLACEMENT,
                    requested=desired["placement"],
                ),
                ServiceOperation(
                    service_id=release.service_id,
                    kind=OperationKind.ROLLOUT,
                    requested=desired["rollout"],
                ),
                ServiceOperation(
                    service_id=release.service_id,
                    kind=OperationKind.OBSERVABILITY,
                    requested=desired["observability"],
                ),
            ]
        )
        candidate = Deployment(
            service_id=release.service_id,
            image_tag="nginx:1.27-alpine",
            commit_sha="kind-e2e-workload-controls",
            status=DeploymentStatus.QUEUED,
        )
        session.add(candidate)
        session.commit()
        candidate_id = candidate.id

    with Session(engine) as session:
        outcome = await run_deployment(
            candidate_id,
            session=session,
            engine=engine,
            agent=object(),
            store=store,
            settings=settings,
            builder=_builder_must_not_run,
        )
        if outcome.status is not DeploymentStatus.LIVE:
            raise RuntimeError(outcome.detail or "application controls did not go live")
        operations = list(
            session.exec(
                select(ServiceOperation).where(ServiceOperation.service_id == release.service_id)
            ).all()
        )
        if {operation.status for operation in operations} != {OperationStatus.HEALTHY}:
            raise RuntimeError("application controls did not become healthy")

    workload_name = dns_label(f"web-{str(candidate_id)[:8]}")
    workload = await api.apps.read_namespaced_deployment(workload_name, release.namespace)
    container = workload.spec.template.spec.containers[0]
    if workload.spec.replicas != 2:
        raise RuntimeError("manual app replica count was not applied")
    if container.resources.requests != {"cpu": "200m", "memory": "128Mi"}:
        raise RuntimeError("manual app resource requests were not applied")
    if container.resources.limits != {"cpu": "500m", "memory": "256Mi"}:
        raise RuntimeError("manual app resource limits were not applied")
    annotations = workload.spec.template.metadata.annotations or {}
    if annotations.get("prometheus.io/scrape") != "true":
        raise RuntimeError("Prometheus scrape annotation was not applied")
    if workload.spec.template.spec.affinity is None:
        raise RuntimeError("manual app anti-affinity was not applied")
    if not workload.spec.template.spec.topology_spread_constraints:
        raise RuntimeError("manual app topology spreading was not applied")
    disruption_budget = await api.policy.read_namespaced_pod_disruption_budget(
        dns_label(f"{workload_name}-pdb"), release.namespace
    )
    if disruption_budget.spec.max_unavailable != 1:
        raise RuntimeError("manual high-availability disruption budget was not applied")
    await _wait_for_ingress(release.host)
    return candidate_id


async def _assert_managed_postgres_controls(
    engine,
    settings: Settings,
    store: BuildLogStore,
    api: AsyncKubernetesApi,
    release: ImportedRelease,
) -> None:
    """Exercise the same immutable-image reconciliation used by the UI.

    A catalog-managed PostgreSQL service is rendered as a CNPG Cluster.  This
    deliberately verifies private read replicas, only-upward storage
    expansion, and (when the caller configured a private object store) a real
    CloudNativePG physical backup.
    """
    with Session(engine) as session:
        state = ServiceOperationsState(
            service_id=release.postgres_service_id,
            desired={
                "read_replicas": {"replicas": 1, "public": False},
                "storage": {"current_size_mb": 1024, "requested_size_mb": 2048},
            },
            pending_reconciliation=True,
            version=1,
        )
        operations = [
            ServiceOperation(
                service_id=release.postgres_service_id,
                kind=OperationKind.READ_REPLICA,
                requested={"replicas": 1, "public": False},
            ),
            ServiceOperation(
                service_id=release.postgres_service_id,
                kind=OperationKind.STORAGE,
                requested={"current_size_mb": 1024, "requested_size_mb": 2048},
            ),
        ]
        if settings.kubernetes_backup_configured:
            backup = ServiceOperation(
                service_id=release.postgres_service_id,
                kind=OperationKind.BACKUP,
                requested={"retention_days": 7},
            )
            session.add(backup)
            session.flush()
            state.desired = {
                **state.desired,
                "backups": {"operation_id": str(backup.id), "retention_days": 7},
            }
        session.add(state)
        session.add_all(operations)
        candidate = Deployment(
            service_id=release.service_id,
            image_tag="nginx:1.27-alpine",
            commit_sha="kind-e2e-managed-postgres",
            status=DeploymentStatus.QUEUED,
        )
        session.add(candidate)
        session.commit()
        candidate_id = candidate.id

    with Session(engine) as session:
        outcome = await run_deployment(
            candidate_id,
            session=session,
            engine=engine,
            agent=object(),
            store=store,
            settings=settings,
            builder=_builder_must_not_run,
        )
        if outcome.status is not DeploymentStatus.LIVE:
            raise RuntimeError(
                outcome.detail or "managed PostgreSQL reconciliation did not go live"
            )
        operations = list(
            session.exec(
                select(ServiceOperation).where(
                    ServiceOperation.service_id == release.postgres_service_id
                )
            ).all()
        )
        if {operation.status for operation in operations} != {OperationStatus.HEALTHY}:
            raise RuntimeError("managed PostgreSQL operations did not become healthy")

    cluster = await api.custom.get_namespaced_custom_object(
        group="postgresql.cnpg.io",
        version="v1",
        namespace=release.namespace,
        plural="clusters",
        name="postgres",
    )
    if not isinstance(cluster, dict) or cluster.get("spec", {}).get("instances") != 2:
        raise RuntimeError("managed PostgreSQL read-replica count was not applied")
    if cluster.get("spec", {}).get("storage", {}).get("size") != "2048Mi":
        raise RuntimeError("managed PostgreSQL storage expansion was not applied")
    if settings.kubernetes_backup_configured:
        backups = await api.custom.list_namespaced_custom_object(
            group="postgresql.cnpg.io",
            version="v1",
            namespace=release.namespace,
            plural="backups",
        )
        backup_items = backups.get("items", []) if isinstance(backups, dict) else []
        if not any(
            isinstance(item, dict)
            and item.get("spec", {}).get("cluster", {}).get("name") == "postgres"
            and item.get("status", {}).get("phase") == "completed"
            for item in backup_items
        ):
            raise RuntimeError("managed PostgreSQL physical backup did not complete")


async def _assert_autoscaling_and_jobs(
    engine,
    settings: Settings,
    store: BuildLogStore,
    api: AsyncKubernetesApi,
    release: ImportedRelease,
) -> None:
    """Exercise HPA, scheduled work, and a bounded one-off Job on Kind.

    The HPA becomes the only replica authority (the manual replica setting is
    cleared), while the application image remains immutable.  The one-off Job
    must complete before the candidate can be promoted; the CronJob merely
    renders its recurring schedule and never waits for clock time in CI.
    """
    with Session(engine) as session:
        state = session.exec(
            select(ServiceOperationsState).where(
                ServiceOperationsState.service_id == release.service_id
            )
        ).one()
        schedule = ServiceOperation(
            service_id=release.service_id,
            kind=OperationKind.SCHEDULE,
            requested={
                "cron": "*/5 * * * *",
                "command": ["/bin/sh", "-c", "echo scheduled"],
                "timeout_seconds": 60,
                "retries": 0,
                "concurrency_policy": "forbid",
            },
        )
        session.add(schedule)
        session.flush()
        # Keep the primitive identifier after this session closes.  The
        # verifier must not later dereference an expired SQLModel instance.
        schedule_id = schedule.id
        autoscaling = {
            "min_replicas": 2,
            "max_replicas": 3,
            "target_cpu_percent": 75,
        }
        job = {
            "command": ["/bin/sh", "-c", "echo one-off"],
            "timeout_seconds": 60,
            "retries": 0,
        }
        state.desired = {
            "autoscaling": autoscaling,
            "schedules": [{"operation_id": str(schedule_id), "spec": schedule.requested}],
            "last_job": job,
        }
        state.pending_reconciliation = True
        state.version += 1
        session.add_all(
            [
                state,
                ServiceOperation(
                    service_id=release.service_id,
                    kind=OperationKind.AUTOSCALING,
                    requested=autoscaling,
                ),
                ServiceOperation(
                    service_id=release.service_id,
                    kind=OperationKind.JOB,
                    requested=job,
                ),
            ]
        )
        candidate = Deployment(
            service_id=release.service_id,
            image_tag="nginx:1.27-alpine",
            commit_sha="kind-e2e-autoscaling-and-jobs",
            status=DeploymentStatus.QUEUED,
        )
        session.add(candidate)
        session.commit()
        candidate_id = candidate.id

    with Session(engine) as session:
        outcome = await run_deployment(
            candidate_id,
            session=session,
            engine=engine,
            agent=object(),
            store=store,
            settings=settings,
            builder=_builder_must_not_run,
        )
        if outcome.status is not DeploymentStatus.LIVE:
            raise RuntimeError(outcome.detail or "HPA and Job controls did not go live")
        operations = list(
            session.exec(
                select(ServiceOperation).where(
                    ServiceOperation.service_id == release.service_id,
                    ServiceOperation.kind.in_(  # type: ignore[attr-defined]
                        [OperationKind.AUTOSCALING, OperationKind.SCHEDULE, OperationKind.JOB]
                    ),
                )
            ).all()
        )
        if len(operations) != 3 or {operation.status for operation in operations} != {
            OperationStatus.HEALTHY
        }:
            raise RuntimeError("HPA and Job controls did not become healthy")

    workload_name = dns_label(f"web-{str(candidate_id)[:8]}")
    hpa = await api.autoscaling.read_namespaced_horizontal_pod_autoscaler(
        dns_label(f"{workload_name}-hpa"), release.namespace
    )
    if hpa.spec.min_replicas != 2 or hpa.spec.max_replicas != 3:
        raise RuntimeError("HorizontalPodAutoscaler limits were not applied")
    cron_name = dns_label(f"{workload_name}-schedule-{schedule_id}", max_length=52)
    cron = await api.batch.read_namespaced_cron_job(cron_name, release.namespace)
    if cron.spec.schedule != "*/5 * * * *":
        raise RuntimeError("scheduled Job was not applied")
    job_status = await api.batch.read_namespaced_job_status(
        dns_label(f"{workload_name}-job"), release.namespace
    )
    if (job_status.status.succeeded or 0) < 1:
        raise RuntimeError("one-off Job did not complete")
    await _wait_for_ingress(release.host)


async def _assert_immutable_kubernetes_restore(
    engine,
    settings: Settings,
    api: AsyncKubernetesApi,
    release: ImportedRelease,
    *,
    target_deployment_id: uuid.UUID,
) -> None:
    """Restore a superseded release by changing only the stable Ingress target."""
    with Session(engine) as session:
        target = session.get(Deployment, target_deployment_id)
        if target is None or target.status is not DeploymentStatus.SUPERSEDED:
            raise RuntimeError("Kubernetes rollback target was not retained as immutable history")
        session.add(
            ServiceOperation(
                service_id=release.service_id,
                kind=OperationKind.ROLLBACK,
                requested={"deployment_id": str(target_deployment_id)},
            )
        )
        session.commit()
        restored = await reconcile_pending_rollbacks(session, settings=settings)
        if restored != 1:
            raise RuntimeError("immutable Kubernetes rollback was not reconciled")
        session.refresh(target)
        if target.status is not DeploymentStatus.LIVE:
            raise RuntimeError("immutable Kubernetes rollback did not restore the target")

    ingress = await api.networking.read_namespaced_ingress("route-web", release.namespace)
    backend = ingress.spec.rules[0].http.paths[0].backend.service
    expected_backend = dns_label(f"web-{str(target_deployment_id)[:8]}")
    if backend.name != expected_backend:
        raise RuntimeError("immutable Kubernetes rollback rebuilt instead of repointing ingress")
    if await asyncio.to_thread(_request_status, release.host) != 200:
        raise RuntimeError("immutable Kubernetes rollback did not preserve the public route")


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
