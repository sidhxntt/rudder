"""build -> run -> healthcheck -> route.

This module is where the failure modes the PRD warns about actually live, so
each one is named at the point it is handled rather than in a comment at the top:

  - two deploys racing            -> the D11 advisory lock and supersede pass
  - health check racing the shift -> the liveness re-check before routing
  - a container dying mid-drain   -> drain failures never fail a live deploy

The invariant that matters: a failed deploy is a no-op from the user's
perspective. The previously live container keeps serving through every failure
path below.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import yaml
from kubernetes_asyncio.client import ApiException
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from rudder_cp.config import Settings
from rudder_cp.logs.store import BuildLogStore
from rudder_cp.models import (
    Deployment,
    DeploymentStatus,
    Domain,
    GitHubImport,
    GitHubImportService,
    Instance,
    InstanceStatus,
    Node,
    NodeStatus,
    Service,
    ServiceOperationsState,
    Volume,
)
from rudder_cp.runtime.kubernetes import AsyncKubernetesApi, KubernetesRuntime, RuntimeSettings
from rudder_cp.runtime.models import ComposeService as KubernetesComposeService
from rudder_cp.runtime.models import KubernetesRelease, dns_label
from rudder_cp.services import scheduler, traefik, variables
from rudder_cp.services.agent_client import AgentClient, AgentError
from rudder_cp.services.builder import BuildFailed, BuildRequest, build_image
from rudder_cp.services.github_app import GitHubAppClient, GitHubAppError
from rudder_cp.services.health import is_still_alive, wait_until_healthy
from rudder_cp.services.locks import service_deploy_lock
from rudder_cp.services.operation_reconciler import (
    mark_runtime_operations_failed,
    mark_runtime_operations_progressing,
    reconcile_runtime_operations,
)

log = logging.getLogger("rudder_cp.deploy")

# Injected so tests can drive the whole path without BuildKit or a git remote.
Builder = Callable[[BuildRequest, BuildLogStore, Settings], Awaitable[object]]


@dataclass(frozen=True)
class DeployOutcome:
    deployment_id: UUID
    status: DeploymentStatus
    detail: str | None = None


async def run_deployment(
    deployment_id: UUID,
    *,
    session: Session,
    engine: Engine,
    agent: AgentClient,
    store: BuildLogStore,
    settings: Settings,
    builder: Builder = build_image,
) -> DeployOutcome:
    """Take one queued Deployment all the way to live, or fail it cleanly."""
    deployment = session.get(Deployment, deployment_id)
    if deployment is None:
        raise ValueError(f"No such deployment: {deployment_id}")
    recovering = deployment.status in {
        DeploymentStatus.BUILDING,
        DeploymentStatus.DEPLOYING,
    }
    if deployment.status is not DeploymentStatus.QUEUED and not recovering:
        # The worker polls, so a terminal row can be seen again.
        return DeployOutcome(deployment_id, deployment.status, "not queued")

    service = session.get(Service, deployment.service_id)
    if service is None:
        return _fail(session, deployment, "The service was deleted before the deploy started.")

    async with service_deploy_lock(engine, service.id) as acquired:
        if not acquired:
            # Another deploy for this service holds the lock. Leave this one
            # queued; the worker will pick it up again once that one finishes.
            return DeployOutcome(deployment_id, DeploymentStatus.QUEUED, "service busy")
        if recovering:
            # A deploy worker can be interrupted after the image or Compose
            # project exists but before the database receives its final state.
            # Preserve its existing log and continue the same immutable release
            # rather than leaving a forever-open SSE stream in the UI.
            if store.exists(deployment.id):
                await store.append(
                    deployment.id,
                    "resuming interrupted deployment from its existing artifact\n",
                )
            else:
                await _open_deployment_log(store, deployment, service)
        else:
            await _open_deployment_log(store, deployment, service)
        outcome = await _deploy_locked(
            deployment,
            service,
            session=session,
            agent=agent,
            store=store,
            settings=settings,
            builder=builder,
            recovering=recovering,
        )
        await _close_deployment_log(store, outcome)
        return outcome


async def _deploy_locked(
    deployment: Deployment,
    service: Service,
    *,
    session: Session,
    agent: AgentClient,
    store: BuildLogStore,
    settings: Settings,
    builder: Builder,
    recovering: bool = False,
) -> DeployOutcome:
    # ---------------------------------------------------------------- build
    deployment.status = DeploymentStatus.BUILDING
    session.add(deployment)
    session.commit()

    managed_image = service.build_config.get("managed_image")
    rollback_image = deployment.image_tag
    git_token: str | None = None
    if not isinstance(managed_image, str) and not isinstance(rollback_image, str):
        imported = session.exec(
            select(GitHubImport).where(GitHubImport.app_service_id == service.id)
        ).first()
        if imported is not None:
            try:
                git_token = await GitHubAppClient(settings).installation_token(
                    imported.installation_id
                )
            except GitHubAppError as exc:
                return _fail(
                    session,
                    deployment,
                    f"Could not authorize the GitHub App installation. {exc}",
                )

    request = BuildRequest(
        deployment_id=deployment.id,
        service_id=service.id,
        source_repo=service.source_repo or "",
        source_branch=service.source_branch,
        commit_sha=deployment.commit_sha,
        dockerfile_path=service.dockerfile_path,
        container_port=service.container_port,
        start_command=service.start_command,
        git_token=git_token,
    )
    if isinstance(rollback_image, str):
        # A rollback row is intentionally queued with its image already set.
        # Recovery gets the same efficient, safe path: the image was already
        # pushed before the control-plane interruption, so rebuilding it would
        # create a needless second candidate.
        await store.append(
            deployment.id,
            (
                f"resuming with immutable image {rollback_image}\n"
                if recovering
                else f"reusing immutable image {rollback_image} for rollback\n"
            ),
        )
        result = type(
            "RollbackImage", (), {"image_tag": rollback_image, "commit_sha": deployment.commit_sha}
        )()
    elif isinstance(managed_image, str):
        result = type("ManagedImage", (), {"image_tag": managed_image, "commit_sha": None})()
    else:
        try:
            result = await builder(request, store, settings)
        except BuildFailed as exc:
            return _fail(session, deployment, str(exc))

    deployment.image_tag = getattr(result, "image_tag", None)
    deployment.commit_sha = getattr(result, "commit_sha", deployment.commit_sha)

    imported = session.exec(
        select(GitHubImport).where(GitHubImport.app_service_id == service.id)
    ).first()
    if imported is not None:
        if settings.runtime == "kubernetes":
            return await _deploy_imported_kubernetes(
                deployment,
                service,
                imported,
                session=session,
                store=store,
                settings=settings,
            )
        return await _deploy_imported_compose(
            deployment,
            service,
            imported,
            session=session,
            agent=agent,
            store=store,
            settings=settings,
            recovering=recovering,
        )

    # ------------------------------------------------------------- deploying
    # Supersede here, not at queue time: an older build that is still running
    # keeps its container alive until this one is actually ready to replace it.
    deployment.status = DeploymentStatus.DEPLOYING
    session.add(deployment)
    _supersede_older(session, deployment)
    session.commit()

    try:
        env = await variables.resolve_service_env(session, service.id)
        node = scheduler.select_node_for_service(session, service)
        # Reserve capacity while the scheduler's row locks are held, then
        # commit before making a remote agent call.  Holding a database
        # transaction open across Docker/image-pull I/O blocks the selected
        # node's heartbeat and can make a healthy node look unavailable.
        node.cpu_allocated += service.cpu_limit
        node.memory_allocated_mb += service.memory_limit_mb
        session.add(node)
        session.commit()
    except Exception as exc:
        # Reference resolution errors are written for the user to read.
        return _fail(session, deployment, str(exc))

    node_agent = agent.for_node(node.ip_address)
    container_name = f"rudder-{service.name}-{str(deployment.id)[:8]}"

    try:
        volumes = {
            f"rudder-volume-{volume.id}": {"bind": volume.mount_path, "mode": "rw"}
            for volume in session.exec(select(Volume).where(Volume.service_id == service.id)).all()
        }
        state = await node_agent.create_container(
            image=deployment.image_tag or "",
            name=container_name,
            env=env,
            container_port=service.container_port,
            cpu_limit=service.cpu_limit,
            memory_limit_mb=service.memory_limit_mb,
            network=settings.docker_network,
            labels={
                "rudder.service": str(service.id),
                "rudder.deployment": str(deployment.id),
            },
            network_aliases=[service.name] if isinstance(managed_image, str) else [],
            volumes=volumes,
            command=service.build_config.get("command") if isinstance(managed_image, str) else None,
        )
    except AgentError as exc:
        _release_node_capacity(session, node.id, service)
        return _fail(session, deployment, f"Could not start the container. {exc}")

    instance = Instance(
        deployment_id=deployment.id,
        node_id=node.id,
        container_id=state.id,
        status=InstanceStatus.STARTING,
        started_at=datetime.now(UTC),
    )
    session.add(instance)
    session.commit()

    # ------------------------------------------------------------- health
    outcome = await wait_until_healthy(
        node_agent,
        state.id,
        path=service.health_check_path,
        port=service.health_check_port or service.container_port,
        settings=settings,
        protocol="tcp" if isinstance(managed_image, str) else "http",
    )
    if not outcome.healthy:
        await _discard(agent, session, instance, drain_seconds=0)
        _release_node_capacity(session, node.id, service)
        return _fail(session, deployment, outcome.reason or "Health check failed.")

    # The container answered 200 at some point in the last few seconds. That is
    # not the same as it being alive right now, and the traffic shift is about
    # to happen. Check again at the moment of the shift.
    if not await is_still_alive(node_agent, state.id):
        await _discard(agent, session, instance, drain_seconds=0)
        _release_node_capacity(session, node.id, service)
        return _fail(
            session,
            deployment,
            "The container passed its health check and then stopped before "
            "traffic could be shifted to it.",
        )

    # ------------------------------------------------------------- shift
    instance.status = InstanceStatus.HEALTHY
    deployment.status = DeploymentStatus.LIVE
    deployment.became_live_at = datetime.now(UTC)
    session.add(instance)
    session.add(deployment)
    _supersede_previously_live(session, deployment)
    session.commit()

    # A successful release stays running as an immutable restore target. A
    # rollback changes the live pointer and Traefik configuration instead of
    # rebuilding or restarting that historical release.
    # Domains resolve through the live Deployment, so routing is regenerated
    # after the status flip, never before it.
    await traefik.render_all(session, settings)

    return DeployOutcome(deployment.id, DeploymentStatus.LIVE)


def _release_node_capacity(session: Session, node_id: UUID, service: Service) -> None:
    """Undo a reservation made before an unsuccessful container start.

    Reservations are committed before network I/O so heartbeats remain
    independent of long pulls.  Every failure before the deployment becomes
    live must therefore return that capacity deterministically.
    """
    node = session.get(Node, node_id)
    if node is None:
        return
    node.cpu_allocated = max(0.0, node.cpu_allocated - service.cpu_limit)
    node.memory_allocated_mb = max(0, node.memory_allocated_mb - service.memory_limit_mb)
    session.add(node)
    session.commit()


async def _deploy_imported_compose(
    deployment: Deployment,
    service: Service,
    imported: GitHubImport,
    *,
    session: Session,
    agent: AgentClient,
    store: BuildLogStore,
    settings: Settings,
    recovering: bool = False,
) -> DeployOutcome:
    """Start an imported application as an isolated candidate Compose project.

    Every candidate has its own Compose namespace.  This lets the old release
    continue serving until the new app container is healthy and Traefik is
    shifted; a failed candidate is simply brought down without changing routes.
    """
    deployment.status = DeploymentStatus.DEPLOYING
    session.add(deployment)
    _supersede_older(session, deployment)
    session.commit()
    try:
        env = await variables.resolve_service_env(session, service.id)
        manifest = await _compose_runtime_manifest(
            session,
            imported=imported,
            app_service=service,
            image=deployment.image_tag or "",
            app_env=env,
            docker_network=settings.docker_network,
        )
    except (ValueError, yaml.YAMLError) as exc:
        return _fail(session, deployment, f"Could not prepare the Compose release. {exc}")

    project_name = _compose_release_name(imported, deployment)

    # A restart can happen after ``compose up`` succeeds but before the
    # control plane creates Instance rows.  Do not reject that real candidate
    # merely because its node has not sent its first post-restart heartbeat
    # yet.  First find the already-running project on every registered agent;
    # only a brand-new release needs a fresh scheduling decision.
    node: Node | None = None
    node_agent: AgentClient | None = None
    states = []
    # ``select_node_for_service`` locks its chosen Node row.  That lock must
    # only cover placement + reservation, never the Docker/Compose request:
    # an agent heartbeat updates the same Node and otherwise waits behind a
    # potentially slow image pull.  Apart from making a healthy node appear
    # unreachable, that can strand the deployment in ``deploying``.
    capacity_reserved = False
    if recovering:
        for candidate in session.exec(select(Node).order_by(Node.hostname)).all():
            candidate_agent = agent.for_node(candidate.ip_address)
            try:
                candidate_states = await candidate_agent.compose_ps(project_name=project_name)
            except AgentError:
                continue
            if candidate_states:
                node = candidate
                node_agent = candidate_agent
                states = candidate_states
                await _append_release_log(
                    store,
                    deployment.id,
                    f"found existing Compose candidate on {candidate.hostname}; resuming release\n",
                )
                break

    if node is None or node_agent is None:
        try:
            # Placement is a precondition for creating a candidate stack.
            # Starting Compose first can orphan live containers when capacity
            # is unavailable.
            node = scheduler.select_node_for_service(session, service)
        except ValueError as exc:
            return _fail(session, deployment, str(exc))
        node_agent = agent.for_node(node.ip_address)
        try:
            # Persist the reservation before contacting the remote agent.  It
            # closes the scheduler transaction and prevents a second release
            # from overbooking this node while Compose is starting.
            node.cpu_allocated += service.cpu_limit
            node.memory_allocated_mb += service.memory_limit_mb
            session.add(node)
            session.commit()
            capacity_reserved = True
            compose_result = await node_agent.compose_up(
                project_name=project_name,
                manifest=manifest,
            )
            # Logging must never hold a real release hostage. In particular, a
            # browser can have several stale SSE readers attached during local
            # development; if a filesystem executor stalls, continue the
            # Compose lifecycle and surface a warning in the control-plane log
            # instead.
            await _append_release_log(store, deployment.id, compose_result.log)
            states = await node_agent.compose_ps(project_name=project_name)
        except AgentError as exc:
            if capacity_reserved:
                _release_node_capacity(session, node.id, service)
            return _fail(session, deployment, f"Could not start the Compose project. {exc}")

    compose_service = service.build_config.get("compose_service", "app")
    if not isinstance(compose_service, str):
        await _compose_down_safely(node_agent, project_name)
        if capacity_reserved:
            _release_node_capacity(session, node.id, service)
        return _fail(session, deployment, "The imported application has no Compose service name.")
    state_by_service = {state.service: state for state in states if state.container_id}
    app_state = state_by_service.get(compose_service)
    if app_state is None:
        await _compose_down_safely(node_agent, project_name)
        if capacity_reserved:
            _release_node_capacity(session, node.id, service)
        return _fail(
            session,
            deployment,
            f"Compose did not report a running container for {compose_service!r}.",
        )

    graph = session.exec(
        select(GitHubImportService).where(GitHubImportService.github_import_id == imported.id)
    )
    mappings = graph.all()
    missing = sorted(
        mapping.compose_service
        for mapping in mappings
        if mapping.compose_service not in state_by_service
    )
    if missing:
        await _compose_down_safely(node_agent, project_name)
        if capacity_reserved:
            _release_node_capacity(session, node.id, service)
        return _fail(
            session,
            deployment,
            "Compose did not report running containers for " + ", ".join(missing) + ".",
        )
    managed_compose_services = (
        {mapping.compose_service for mapping in mappings} if mappings else {compose_service}
    )
    instances_by_service = {
        compose_name: Instance(
            deployment_id=deployment.id,
            node_id=node.id,
            container_id=state_by_service[compose_name].container_id,
            compose_service=compose_name,
            status=InstanceStatus.STARTING,
            started_at=datetime.now(UTC),
        )
        for compose_name in managed_compose_services
    }
    for instance in instances_by_service.values():
        session.add(instance)

    # Recovery may have found a candidate started by a process that exited
    # before reserving capacity. Fresh candidates were reserved above, before
    # the remote call, so never charge them twice.
    if not capacity_reserved:
        node.cpu_allocated += service.cpu_limit
        node.memory_allocated_mb += service.memory_limit_mb
        session.add(node)

    session.commit()

    outcome = await wait_until_healthy(
        node_agent,
        app_state.container_id,
        path=service.health_check_path,
        port=service.health_check_port or service.container_port,
        settings=settings,
    )
    if not outcome.healthy:
        for instance in instances_by_service.values():
            await _discard(agent, session, instance, drain_seconds=0)
        await _compose_down_safely(node_agent, project_name)
        # Compose candidates reserve the main service's capacity immediately
        # before health checks. A rejected candidate must release that single
        # reservation; otherwise repeated failed imports eventually make an
        # otherwise idle node look full.
        _release_node_capacity(session, node.id, service)
        return _fail(
            session, deployment, outcome.reason or "Compose application health check failed."
        )
    stopped = [
        compose_name
        for compose_name, state in state_by_service.items()
        if compose_name in instances_by_service
        and not await is_still_alive(node_agent, state.container_id)
    ]
    if stopped:
        for instance in instances_by_service.values():
            await _discard(agent, session, instance, drain_seconds=0)
        await _compose_down_safely(node_agent, project_name)
        _release_node_capacity(session, node.id, service)
        return _fail(
            session,
            deployment,
            "Compose services stopped before traffic could be shifted: " + ", ".join(stopped) + ".",
        )

    for mapping in mappings:
        mapping.container_id = state_by_service[mapping.compose_service].container_id
        session.add(mapping)
    for instance in instances_by_service.values():
        instance.status = InstanceStatus.HEALTHY
        session.add(instance)
    deployment.status = DeploymentStatus.LIVE
    deployment.became_live_at = datetime.now(UTC)
    session.add(deployment)
    _supersede_previously_live(session, deployment)
    # Keep each Compose candidate alive as an immutable rollback target.
    session.commit()
    await traefik.render_all(session, settings)
    return DeployOutcome(deployment.id, DeploymentStatus.LIVE)


async def _deploy_imported_kubernetes(
    deployment: Deployment,
    service: Service,
    imported: GitHubImport,
    *,
    session: Session,
    store: BuildLogStore,
    settings: Settings,
) -> DeployOutcome:
    """Release an imported Compose graph through the Kubernetes runtime.

    Kubernetes owns pod placement and readiness.  The existing Rudder node is
    retained as an accounting anchor for the current ``Instance`` schema and
    host health UI; it is not used to schedule individual pods.
    """
    deployment.status = DeploymentStatus.DEPLOYING
    session.add(deployment)
    _supersede_older(session, deployment)
    session.commit()

    anchor_node = session.exec(
        select(Node).where(Node.status == NodeStatus.HEALTHY).order_by(Node.hostname)
    ).first()
    if anchor_node is None:
        return _fail(
            session,
            deployment,
            "No healthy Rudder node is available to account for this Kubernetes release.",
        )
    api: AsyncKubernetesApi | None = None
    mappings: list[GitHubImportService] = []
    try:
        app_env = await variables.resolve_service_env(session, service.id)
        manifest = await _compose_runtime_manifest(
            session,
            imported=imported,
            app_service=service,
            image=deployment.image_tag or "",
            app_env=app_env,
            docker_network=settings.docker_network,
        )
        document = yaml.safe_load(manifest)
        if not isinstance(document, dict) or not isinstance(document.get("services"), dict):
            raise ValueError("stored manifest has no services mapping")
        services_document = document["services"]
        mappings = session.exec(
            select(GitHubImportService).where(GitHubImportService.github_import_id == imported.id)
        ).all()
        if not mappings:
            raise ValueError("the imported application has no service graph")
        members: list[KubernetesComposeService] = []
        for mapping in mappings:
            raw = services_document.get(mapping.compose_service)
            member_service = session.get(Service, mapping.service_id)
            if not isinstance(raw, dict) or member_service is None:
                raise ValueError(f"stored manifest is missing {mapping.compose_service!r}")
            image = raw.get("image")
            if not isinstance(image, str) or not image:
                raise ValueError(f"Kubernetes release has no image for {mapping.compose_service!r}")
            command = _compose_command(raw.get("command"))
            volume = session.exec(
                select(Volume).where(Volume.service_id == member_service.id)
            ).first()
            port = member_service.container_port or _compose_exposed_port(raw)
            member_environment = _merge_compose_environment(
                raw.get("environment"),
                await variables.resolve_service_env(session, member_service.id),
            )
            public_domain = None
            if mapping.is_public:
                public_domain = session.exec(
                    select(Domain)
                    .where(Domain.service_id == member_service.id)
                    .order_by(Domain.is_system.desc(), Domain.created_at)
                ).first()
            operations_state = session.exec(
                select(ServiceOperationsState).where(
                    ServiceOperationsState.service_id == member_service.id
                )
            ).first()
            members.append(
                KubernetesComposeService(
                    name=mapping.compose_service,
                    image=image,
                    port=port,
                    command=command,
                    environment=member_environment,
                    public=mapping.is_public,
                    public_host=public_domain.hostname if public_domain is not None else None,
                    stateful=mapping.role
                    in {"database", "cache", "broker", "search", "storage"},
                    volume_mount_path=volume.mount_path if volume is not None else None,
                    operations=operations_state.desired if operations_state is not None else {},
                )
            )
        namespace = dns_label(
            f"{settings.kubernetes_namespace_prefix}-{service.environment_id.hex[:12]}"
        )
        runtime_settings = RuntimeSettings(
            local_domain=settings.kubernetes_local_domain,
            ingress_class=settings.kubernetes_ingress_class,
            readiness_timeout_seconds=settings.kubernetes_readiness_timeout_seconds,
        )
        api = await AsyncKubernetesApi.from_kubeconfig(
            runtime_settings,
            kubeconfig_path=settings.kubernetes_kubeconfig,
        )
        runtime = KubernetesRuntime(api, runtime_settings)
        mark_runtime_operations_progressing(
            session, service_ids=[mapping.service_id for mapping in mappings]
        )
        await _append_release_log(
            store,
            deployment.id,
            f"applying Kubernetes release in namespace {namespace}\n",
        )
        result = await runtime.apply(
            KubernetesRelease(
                namespace=namespace,
                release_id=str(deployment.id),
                services=tuple(members),
            ),
            project_id=str(imported.project_id),
            environment_id=str(service.environment_id),
            on_progress=lambda text: _append_release_log(store, deployment.id, text),
        )
    except (ApiException, OSError, ValueError, yaml.YAMLError, RuntimeError) as exc:
        if mappings:
            mark_runtime_operations_failed(
                session,
                service_ids=[mapping.service_id for mapping in mappings],
                reason=f"Kubernetes release failed before readiness: {exc}",
            )
        return _fail(session, deployment, f"Could not apply Kubernetes release. {exc}")
    finally:
        if api is not None:
            # The async Kubernetes client owns a network session. A deployment
            # failure must not leak it and eventually starve later releases.
            with suppress(Exception):
                await api.close()

    for mapping in mappings:
        pod_id = result.pod_ids[mapping.compose_service]
        mapping.container_id = pod_id
        session.add(mapping)
        session.add(
            Instance(
                deployment_id=deployment.id,
                node_id=anchor_node.id,
                container_id=pod_id,
                compose_service=mapping.compose_service,
                status=InstanceStatus.HEALTHY,
                started_at=datetime.now(UTC),
            )
        )
        reconcile_runtime_operations(
            session,
            service_id=mapping.service_id,
            runtime_observed=result.operation_observed.get(mapping.compose_service, {}),
        )
    deployment.status = DeploymentStatus.LIVE
    deployment.became_live_at = datetime.now(UTC)
    session.add(deployment)
    _supersede_previously_live(session, deployment)
    session.commit()
    await _append_release_log(
        store,
        deployment.id,
        "Kubernetes release is ready; public routes were promoted after readiness.\n",
    )
    return DeployOutcome(deployment.id, DeploymentStatus.LIVE)


# --------------------------------------------------------------------- helpers


async def _open_deployment_log(
    store: BuildLogStore, deployment: Deployment, service: Service
) -> None:
    """Every deployment gets a readable lifecycle log, including add-ons."""
    await store.open_log(deployment.id)
    managed_image = service.build_config.get("managed_image")
    if deployment.image_tag:
        await store.append(
            deployment.id,
            f"starting rollback from immutable image {deployment.image_tag}\n",
        )
    elif isinstance(managed_image, str):
        await store.append(
            deployment.id,
            f"using managed image {managed_image}; no source build is required\n"
            f"starting private service {service.name}\n",
        )
    else:
        await store.append(
            deployment.id,
            f"starting source build for {service.source_repo or service.name}\n",
        )


async def _close_deployment_log(store: BuildLogStore, outcome: DeployOutcome) -> None:
    if outcome.status is DeploymentStatus.LIVE:
        await store.append(outcome.deployment_id, "deployment is live\n")
        await store.close_log(outcome.deployment_id, "succeeded")
        return

    reason = outcome.detail or "deployment did not reach live"
    await store.append(outcome.deployment_id, f"DEPLOYMENT FAILED: {reason}\n")
    await store.close_log(outcome.deployment_id, "failed")


async def _append_release_log(store: BuildLogStore, deployment_id: UUID, text: str) -> None:
    """Append Compose output without allowing an I/O stall to freeze deployment."""
    try:
        await asyncio.wait_for(store.append(deployment_id, text), timeout=2)
    except TimeoutError:
        log.warning("timed out appending Compose output for deployment %s", deployment_id)


def _supersede_older(session: Session, current: Deployment) -> None:
    """Abandon in-flight Deployments that this one has overtaken. D11.

    Strictly OLDER only. Superseding every other non-terminal deployment would
    also kill deployments queued *after* this one, which means the newest push
    gets silently dropped and stale code stays live — the exact opposite of what
    the user asked for. Ordering is (created_at, id): timestamps can tie, ids
    cannot.
    """
    others = session.exec(
        select(Deployment).where(
            Deployment.service_id == current.service_id,
            Deployment.id != current.id,
            Deployment.status.in_(  # type: ignore[attr-defined]
                [
                    DeploymentStatus.QUEUED,
                    DeploymentStatus.BUILDING,
                    DeploymentStatus.DEPLOYING,
                ]
            ),
        )
    ).all()
    for deployment in others:
        if _order(deployment) < _order(current):
            deployment.status = DeploymentStatus.SUPERSEDED
            deployment.error_message = "Superseded by a newer deploy."
            session.add(deployment)


def _supersede_previously_live(session: Session, current: Deployment) -> None:
    """The version this one replaced is no longer live.

    Without this, a service accumulates several Deployments in `live` and
    anything reading "the live deployment" has to guess between them.
    """
    previous = session.exec(
        select(Deployment).where(
            Deployment.service_id == current.service_id,
            Deployment.id != current.id,
            Deployment.status == DeploymentStatus.LIVE,
        )
    ).all()
    for deployment in previous:
        deployment.status = DeploymentStatus.SUPERSEDED
        session.add(deployment)


def _order(deployment: Deployment) -> tuple[datetime, UUID]:
    created = deployment.created_at
    if created.tzinfo is None:
        # SQLite hands back naive datetimes; Postgres does not.
        created = created.replace(tzinfo=UTC)
    return created, deployment.id


async def _drain_previous(
    agent: AgentClient,
    session: Session,
    service_id: UUID,
    *,
    keep_deployment_id: UUID,
    settings: Settings,
) -> None:
    """Stop the containers the new deployment replaced. D10.

    Runs after traffic has already shifted. A failure here is logged and
    swallowed: the new version is live and serving, and turning a leaked
    container into a failed deploy would be a strictly worse outcome.
    """
    previous = session.exec(
        select(Instance)
        .join(Deployment, Deployment.id == Instance.deployment_id)  # type: ignore[arg-type]
        .where(
            Deployment.service_id == service_id,
            Deployment.id != keep_deployment_id,
            Instance.status.in_(  # type: ignore[attr-defined]
                [InstanceStatus.HEALTHY, InstanceStatus.STARTING, InstanceStatus.UNHEALTHY]
            ),
        )
    ).all()
    for instance in previous:
        instance.status = InstanceStatus.DRAINING
        session.add(instance)
    session.commit()

    for instance in previous:
        await _discard(agent, session, instance, drain_seconds=settings.drain_seconds)
        # Exactly one instance per prior deployment belongs to this service.
        # Its reservation was made when that deployment became a candidate, so
        # return it only after the old container has been drained.
        service = session.get(Service, service_id)
        if service is not None:
            _release_node_capacity(session, instance.node_id, service)


async def _discard(
    agent: AgentClient,
    session: Session,
    instance: Instance,
    *,
    drain_seconds: float,
) -> None:
    if instance.container_id:
        try:
            node = session.get(Node, instance.node_id)
            if node is None:
                raise AgentError(f"node {instance.node_id} no longer exists")
            await agent.for_node(node.ip_address).remove(
                instance.container_id, drain_seconds=drain_seconds
            )
        except AgentError as exc:
            log.warning("could not remove container %s: %s", instance.container_id, exc)
    instance.status = InstanceStatus.STOPPED
    instance.stopped_at = datetime.now(UTC)
    session.add(instance)
    session.commit()


async def _compose_runtime_manifest(
    session: Session,
    *,
    imported: GitHubImport,
    app_service: Service,
    image: str,
    app_env: dict[str, str],
    docker_network: str,
) -> str:
    """Inject the immutable image, secret env, and shared Traefik network."""
    document = yaml.safe_load(imported.compose_manifest)
    if not isinstance(document, dict) or not isinstance(document.get("services"), dict):
        raise ValueError("stored manifest has no services mapping")
    services = document["services"]
    compose_name = app_service.build_config.get("compose_service", "app")
    app = services.get(compose_name)
    if not isinstance(compose_name, str) or not isinstance(app, dict):
        raise ValueError("stored manifest does not contain the imported application service")
    app.pop("build", None)
    app["image"] = image
    app["environment"] = _merge_compose_environment(app.get("environment"), app_env)

    # Generated workers/schedulers and repository Compose services that share
    # the app build must use the one immutable image BuildKit produced for this
    # release. Compose has no checkout context at runtime, so leaving `build:`
    # here would make those private processes fail independently of the app.
    for raw_service in services.values():
        if isinstance(raw_service, dict) and "build" in raw_service:
            raw_service.pop("build", None)
            raw_service["image"] = image

    graph = session.exec(
        select(GitHubImportService).where(GitHubImportService.github_import_id == imported.id)
    ).all()
    for mapping in graph:
        if mapping.service_id == app_service.id:
            continue
        sibling = services.get(mapping.compose_service)
        service = session.get(Service, mapping.service_id)
        if isinstance(sibling, dict) and service is not None:
            sibling["environment"] = _merge_compose_environment(
                sibling.get("environment"),
                await variables.resolve_service_env(session, service.id),
            )

    document["networks"] = {
        "rudder": {"external": True, "name": docker_network},
    }
    for raw_service in services.values():
        if not isinstance(raw_service, dict):
            continue
        raw_service["networks"] = ["default", "rudder"]
    return yaml.safe_dump(document, sort_keys=False)


def _compose_command(value: object) -> tuple[str, ...] | None:
    if isinstance(value, str):
        # Kubernetes ``command`` does not run a shell implicitly. Keep the
        # Compose string semantics rather than splitting quoted arguments.
        return ("/bin/sh", "-c", value)
    if isinstance(value, list) and all(isinstance(item, (str, int, float)) for item in value):
        return tuple(str(item) for item in value)
    return None


def _merge_compose_environment(
    raw_environment: object, overrides: dict[str, str]
) -> dict[str, str]:
    """Keep reviewed Compose defaults while Rudder variables take precedence.

    A repository's Compose manifest is part of the approved release contract.
    Replacing its ``environment`` block with an empty Rudder-variable mapping
    silently breaks common images such as Postgres.  Rudder-managed variables
    remain authoritative so secrets and references can still override defaults.
    """
    environment: dict[str, str] = {}
    if isinstance(raw_environment, dict):
        environment = {
            str(key): str(value)
            for key, value in raw_environment.items()
            if isinstance(key, str) and value is not None
        }
    elif isinstance(raw_environment, list):
        for item in raw_environment:
            if not isinstance(item, str) or "=" not in item:
                continue
            key, value = item.split("=", 1)
            if key:
                environment[key] = value
    environment.update(overrides)
    return environment


def _compose_exposed_port(raw_service: dict[object, object]) -> int | None:
    expose = raw_service.get("expose")
    values = [expose] if isinstance(expose, (str, int)) else expose
    if not isinstance(values, list) or not values:
        return None
    try:
        port = int(str(values[0]).split("/", 1)[0])
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= 65535 else None


def _compose_release_name(imported: GitHubImport, deployment: Deployment) -> str:
    return f"{imported.compose_project_name}-{str(deployment.id)[:8]}"


async def _compose_down_safely(agent: AgentClient, project_name: str) -> None:
    try:
        await agent.compose_down(project_name=project_name)
    except AgentError as exc:
        log.warning("could not remove Compose project %s: %s", project_name, exc)


async def _down_previous_compose_releases(
    agent: AgentClient,
    session: Session,
    imported: GitHubImport,
    *,
    keep_deployment_id: UUID,
) -> None:
    previous = session.exec(
        select(Deployment).where(
            Deployment.service_id == imported.app_service_id,
            Deployment.id != keep_deployment_id,
            Deployment.status == DeploymentStatus.SUPERSEDED,
        )
    ).all()
    for deployment in previous:
        instance = session.exec(
            select(Instance).where(Instance.deployment_id == deployment.id)
        ).first()
        if instance is None:
            continue
        node = session.get(Node, instance.node_id)
        if node is not None:
            await _compose_down_safely(
                agent.for_node(node.ip_address), _compose_release_name(imported, deployment)
            )


def _fail(session: Session, deployment: Deployment, reason: str) -> DeployOutcome:
    deployment.status = DeploymentStatus.FAILED
    deployment.error_message = reason
    session.add(deployment)
    session.commit()
    return DeployOutcome(deployment.id, DeploymentStatus.FAILED, reason)
