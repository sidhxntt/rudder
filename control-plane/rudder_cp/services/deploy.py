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

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import yaml
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from rudder_cp.config import Settings
from rudder_cp.logs.store import BuildLogStore
from rudder_cp.models import (
    Deployment,
    DeploymentStatus,
    GitHubImport,
    GitHubImportService,
    Instance,
    InstanceStatus,
    Node,
    Service,
    Volume,
)
from rudder_cp.services import traefik, variables
from rudder_cp.services.agent_client import AgentClient, AgentError
from rudder_cp.services.builder import BuildFailed, BuildRequest, build_image
from rudder_cp.services.github_app import GitHubAppClient, GitHubAppError
from rudder_cp.services.health import is_still_alive, wait_until_healthy
from rudder_cp.services.locks import service_deploy_lock

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
    if deployment.status is not DeploymentStatus.QUEUED:
        # The worker polls, so the same row can be picked up twice.
        return DeployOutcome(deployment_id, deployment.status, "not queued")

    service = session.get(Service, deployment.service_id)
    if service is None:
        return _fail(session, deployment, "The service was deleted before the deploy started.")

    async with service_deploy_lock(engine, service.id) as acquired:
        if not acquired:
            # Another deploy for this service holds the lock. Leave this one
            # queued; the worker will pick it up again once that one finishes.
            return DeployOutcome(deployment_id, DeploymentStatus.QUEUED, "service busy")
        await _open_deployment_log(store, deployment, service)
        outcome = await _deploy_locked(
            deployment,
            service,
            session=session,
            agent=agent,
            store=store,
            settings=settings,
            builder=builder,
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
) -> DeployOutcome:
    # ---------------------------------------------------------------- build
    deployment.status = DeploymentStatus.BUILDING
    session.add(deployment)
    session.commit()

    managed_image = service.build_config.get("managed_image")
    git_token: str | None = None
    if not isinstance(managed_image, str):
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
    if isinstance(managed_image, str):
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
        return await _deploy_imported_compose(
            deployment,
            service,
            imported,
            session=session,
            agent=agent,
            store=store,
            settings=settings,
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
    except Exception as exc:
        # Reference resolution errors are written for the user to read.
        return _fail(session, deployment, str(exc))

    node = _phase1_node(session, settings)
    container_name = f"rudder-{service.name}-{str(deployment.id)[:8]}"

    try:
        volumes = {
            f"rudder-volume-{volume.id}": {"bind": volume.mount_path, "mode": "rw"}
            for volume in session.exec(select(Volume).where(Volume.service_id == service.id)).all()
        }
        state = await agent.create_container(
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
        agent,
        state.id,
        path=service.health_check_path,
        port=service.health_check_port or service.container_port,
        settings=settings,
        protocol="tcp" if isinstance(managed_image, str) else "http",
    )
    if not outcome.healthy:
        await _discard(agent, session, instance, drain_seconds=0)
        return _fail(session, deployment, outcome.reason or "Health check failed.")

    # The container answered 200 at some point in the last few seconds. That is
    # not the same as it being alive right now, and the traffic shift is about
    # to happen. Check again at the moment of the shift.
    if not await is_still_alive(agent, state.id):
        await _discard(agent, session, instance, drain_seconds=0)
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

    # Domains resolve through the live Deployment, so routing must be regenerated
    # after the status flip, never before it.
    await traefik.render_all(session, settings)

    await _drain_previous(
        agent, session, service.id, keep_deployment_id=deployment.id, settings=settings
    )
    await traefik.render_all(session, settings)

    return DeployOutcome(deployment.id, DeploymentStatus.LIVE)


async def _deploy_imported_compose(
    deployment: Deployment,
    service: Service,
    imported: GitHubImport,
    *,
    session: Session,
    agent: AgentClient,
    store: BuildLogStore,
    settings: Settings,
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
    try:
        compose_result = await agent.compose_up(project_name=project_name, manifest=manifest)
        await store.append(deployment.id, compose_result.log)
        states = await agent.compose_ps(project_name=project_name)
    except AgentError as exc:
        return _fail(session, deployment, f"Could not start the Compose project. {exc}")

    compose_service = service.build_config.get("compose_service", "app")
    if not isinstance(compose_service, str):
        await _compose_down_safely(agent, project_name)
        return _fail(session, deployment, "The imported application has no Compose service name.")
    state_by_service = {state.service: state for state in states if state.container_id}
    app_state = state_by_service.get(compose_service)
    if app_state is None:
        await _compose_down_safely(agent, project_name)
        return _fail(
            session,
            deployment,
            f"Compose did not report a running container for {compose_service!r}.",
        )

    node = _phase1_node(session, settings)
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
        await _compose_down_safely(agent, project_name)
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
            status=InstanceStatus.STARTING,
            started_at=datetime.now(UTC),
        )
        for compose_name in managed_compose_services
    }
    for instance in instances_by_service.values():
        session.add(instance)
    session.commit()

    outcome = await wait_until_healthy(
        agent,
        app_state.container_id,
        path=service.health_check_path,
        port=service.health_check_port or service.container_port,
        settings=settings,
    )
    if not outcome.healthy:
        for instance in instances_by_service.values():
            await _discard(agent, session, instance, drain_seconds=0)
        await _compose_down_safely(agent, project_name)
        return _fail(
            session, deployment, outcome.reason or "Compose application health check failed."
        )
    stopped = [
        compose_name
        for compose_name, state in state_by_service.items()
        if compose_name in instances_by_service
        and not await is_still_alive(agent, state.container_id)
    ]
    if stopped:
        for instance in instances_by_service.values():
            await _discard(agent, session, instance, drain_seconds=0)
        await _compose_down_safely(agent, project_name)
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
    session.commit()
    await traefik.render_all(session, settings)

    await _drain_previous(
        agent, session, service.id, keep_deployment_id=deployment.id, settings=settings
    )
    await _down_previous_compose_releases(
        agent, session, imported, keep_deployment_id=deployment.id
    )
    await traefik.render_all(session, settings)
    return DeployOutcome(deployment.id, DeploymentStatus.LIVE)


# --------------------------------------------------------------------- helpers


async def _open_deployment_log(
    store: BuildLogStore, deployment: Deployment, service: Service
) -> None:
    """Every deployment gets a readable lifecycle log, including add-ons."""
    await store.open_log(deployment.id)
    managed_image = service.build_config.get("managed_image")
    if isinstance(managed_image, str):
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


async def _discard(
    agent: AgentClient,
    session: Session,
    instance: Instance,
    *,
    drain_seconds: float,
) -> None:
    if instance.container_id:
        try:
            await agent.remove(instance.container_id, drain_seconds=drain_seconds)
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
    app["environment"] = app_env

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
            sibling["environment"] = await variables.resolve_service_env(session, service.id)

    document["networks"] = {
        "rudder": {"external": True, "name": docker_network},
    }
    for raw_service in services.values():
        if not isinstance(raw_service, dict):
            continue
        raw_service["networks"] = ["default", "rudder"]
    return yaml.safe_dump(document, sort_keys=False)


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
        await _compose_down_safely(agent, _compose_release_name(imported, deployment))


def _fail(session: Session, deployment: Deployment, reason: str) -> DeployOutcome:
    deployment.status = DeploymentStatus.FAILED
    deployment.error_message = reason
    session.add(deployment)
    session.commit()
    return DeployOutcome(deployment.id, DeploymentStatus.FAILED, reason)


def _phase1_node(session: Session, settings: Settings) -> Node:
    """Phase 1 runs everything on one node. Phase 2 replaces this with a scheduler.

    The row exists so Instance.node_id has a real target from day one, which is
    what keeps the Phase 2 change confined to placement.
    """
    node = session.exec(select(Node).where(Node.hostname == "localhost")).first()
    if node is None:
        node = Node(hostname="localhost", ip_address="127.0.0.1")
        session.add(node)
        session.commit()
        session.refresh(node)
    return node
