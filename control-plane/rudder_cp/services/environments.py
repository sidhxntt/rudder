"""Domain logic for environments.

Kubernetes namespaces and NetworkPolicies are the environment-isolation
boundary.  The previous WireGuard CIDR allocator was removed in Phase 4.

Takes ``Session`` as an argument. Never imports FastAPI.
"""

import asyncio
import copy
import uuid

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from rudder_cp.config import Settings
from rudder_cp.models import (
    Deployment,
    DeploymentStatus,
    Environment,
    GitHubImport,
    GitHubImportService,
    Project,
    Service,
    ServiceManagedCapabilities,
    Variable,
    Volume,
)
from rudder_cp.runtime.targets import load_kubernetes_client
from rudder_cp.schemas.common import (
    ConflictError,
    NotFoundError,
    RudderError,
)
from rudder_cp.schemas.environment import (
    EnvironmentClone,
    EnvironmentCreate,
    EnvironmentReplace,
    EnvironmentUpdate,
)
from rudder_cp.services import domains, services, traefik
from rudder_cp.services.agent_client import AgentClient
from rudder_cp.services.github_app import GitHubAppClient
from rudder_cp.services.kubernetes_namespace import environment_namespace

ENVIRONMENT_NAME_TAKEN = "environment_name_taken"


class KubernetesNamespaceTeardownError(RudderError):
    """Kubernetes teardown did not complete, so catalog state is retryable."""

    status_code = 503

    def __init__(self, *, namespace: str, reason: str) -> None:
        super().__init__(
            "Kubernetes namespace teardown did not complete. Retry the delete request.",
            code="kubernetes_namespace_teardown_failed",
            details={"namespace": namespace, "reason": reason, "retryable": True},
        )


async def list_environments(session: Session, project_id: uuid.UUID) -> list[Environment]:
    project = _require_project(session, project_id)
    rows = session.exec(
        select(Environment)
        .where(Environment.project_id == project.id)
        .order_by(Environment.name)
    ).all()
    return list(rows)


async def get_environment(session: Session, environment_id: uuid.UUID) -> Environment:
    return _require_environment(session, environment_id)


async def create_environment(
    session: Session, project_id: uuid.UUID, payload: EnvironmentCreate
) -> Environment:
    project = _require_project(session, project_id)
    environment = await create_environment_row(session, project=project, payload=payload)
    session.commit()
    session.refresh(environment)
    return environment


async def create_environment_row(
    session: Session, *, project: Project, payload: EnvironmentCreate
) -> Environment:
    """Insert an environment. Does not commit.

    Split out so project creation can make a project and its ``production``
    environment in one transaction.
    """
    environment = Environment(
        project_id=project.id,
        name=payload.name,
        is_production=payload.is_production,
    )
    session.add(environment)
    _flush_or_conflict(session, project_id=project.id, name=environment.name)
    return environment


async def clone_environment(
    session: Session, source_environment_id: uuid.UUID, payload: EnvironmentClone
) -> Environment:
    """Copy a service graph into a fresh environment in one database transaction.

    Runtime history and user-owned domains are intentionally absent.  Volumes
    retain their declaration but never their node affinity or data; Kubernetes
    therefore provisions new PVCs on the first deploy.
    """
    source = _require_environment(session, source_environment_id)
    project = _require_project(session, source.project_id)
    target = Environment(
        project_id=project.id,
        name=payload.name,
        is_production=False,
        github_pr_number=payload.github_pr_number,
    )
    try:
        session.add(target)
        _flush_or_conflict(session, project_id=project.id, name=target.name)
        copied: dict[uuid.UUID, Service] = {}
        source_services = list(
            session.exec(select(Service).where(Service.environment_id == source.id)).all()
        )
        for original in source_services:
            data = {
                column.name: getattr(original, column.name)
                for column in Service.__table__.columns
                if column.name not in {"id", "environment_id", "created_at"}
            }
            # JSON columns are mutable Python objects.  A cloned service must
            # never share a build_config dict with the source identity map.
            data["build_config"] = copy.deepcopy(data["build_config"])
            if payload.source_branch is not None and data["source_repo"]:
                data["source_branch"] = payload.source_branch
            copied_service = Service(environment_id=target.id, **data)
            session.add(copied_service)
            session.flush()
            copied[original.id] = copied_service
            await domains.create_system_domain(
                session, environment=target, service=copied_service
            )

        for original_id, copied_service in copied.items():
            source_variables = session.exec(
                select(Variable).where(Variable.service_id == original_id)
            ).all()
            for variable in source_variables:
                session.add(
                    Variable(
                        service_id=copied_service.id,
                        key=variable.key,
                        value_encrypted=variable.value_encrypted,
                        is_reference=variable.is_reference,
                    )
                )
            for capability in session.exec(
                select(ServiceManagedCapabilities).where(
                    ServiceManagedCapabilities.service_id == original_id
                )
            ).all():
                session.add(
                    ServiceManagedCapabilities(
                        service_id=copied_service.id,
                        database_engine=capability.database_engine,
                        data_role=capability.data_role,
                        allowed_job_commands=copy.deepcopy(capability.allowed_job_commands),
                        source=capability.source,
                    )
                )
            source_volumes = session.exec(
                select(Volume).where(Volume.service_id == original_id)
            ).all()
            for volume in source_volumes:
                session.add(
                    Volume(
                        service_id=copied_service.id,
                        mount_path=volume.mount_path,
                        size_mb=volume.size_mb,
                        node_id=None,
                    )
                )

        # Imported Compose releases need their graph mapping rewired as well.
        # Without this, a clone of an imported project has all the visible
        # services but cannot form a Kubernetes/Compose release at deploy time.
        source_imports = list(
            session.exec(
                select(GitHubImport).where(GitHubImport.app_service_id.in_(list(copied)))  # type: ignore[attr-defined]
            ).all()
        )
        for source_import in source_imports:
            mappings = list(
                session.exec(
                    select(GitHubImportService).where(
                        GitHubImportService.github_import_id == source_import.id
                    )
                ).all()
            )
            if any(mapping.service_id not in copied for mapping in mappings):
                continue
            cloned_import = GitHubImport(
                installation_id=source_import.installation_id,
                repository=source_import.repository,
                branch=payload.source_branch or source_import.branch,
                compose_source=source_import.compose_source,
                compose_manifest=source_import.compose_manifest,
                # The historical project-level name is intentionally not
                # reusable: concurrent production and PR Compose releases
                # must never share a Docker project namespace.
                compose_project_name=f"rudder-{target.id.hex[:16]}",
                project_id=target.project_id,
                app_service_id=copied[source_import.app_service_id].id,
                postgres_service_id=(
                    copied[source_import.postgres_service_id].id
                    if source_import.postgres_service_id else None
                ),
                redis_service_id=(
                    copied[source_import.redis_service_id].id
                    if source_import.redis_service_id else None
                ),
            )
            session.add(cloned_import)
            session.flush()
            for mapping in mappings:
                cloned_service = copied[mapping.service_id]
                managed_by = cloned_service.build_config.get("managed_by_service_id")
                if isinstance(managed_by, str):
                    try:
                        owner = copied[uuid.UUID(managed_by)]
                    except (KeyError, ValueError):
                        owner = None
                    if owner is not None:
                        cloned_service.build_config["managed_by_service_id"] = str(owner.id)
                        session.add(cloned_service)
                session.add(
                    GitHubImportService(
                        github_import_id=cloned_import.id,
                        service_id=cloned_service.id,
                        compose_service=mapping.compose_service,
                        role=mapping.role,
                        is_public=mapping.is_public,
                    )
                )
        session.commit()
        session.refresh(target)
        return target
    except Exception:
        session.rollback()
        raise


async def update_environment(
    session: Session, environment_id: uuid.UUID, payload: EnvironmentUpdate
) -> Environment:
    environment = _require_environment(session, environment_id)
    data = payload.model_dump(exclude_unset=True)
    return await _apply_environment_write(session, environment=environment, data=data)


async def replace_environment(
    session: Session, environment_id: uuid.UUID, payload: EnvironmentReplace
) -> Environment:
    """PUT. All writable environment fields are replaced."""
    environment = _require_environment(session, environment_id)
    return await _apply_environment_write(
        session, environment=environment, data=payload.model_dump()
    )


async def delete_environment(
    session: Session, environment_id: uuid.UUID, *, agent: AgentClient, settings: Settings
) -> None:
    """Delete an environment and everything inside it. See ``purge_environment``."""
    environment = _require_environment(session, environment_id)
    service_ids = list(
        session.exec(select(Service.id).where(Service.environment_id == environment.id)).all()
    )
    if settings.runtime != "kubernetes":
        await services.remove_runtime_containers(
            session, service_ids=service_ids, agent=agent, settings=settings
        )
    await remove_environment_namespace(environment, settings)
    await purge_environment(session, environment)
    session.commit()
    await traefik.render_all(session, settings)


async def remove_environment_namespace(environment: Environment, settings: Settings) -> None:
    """Delete the Kubernetes isolation boundary before forgetting its DB row."""
    if settings.runtime != "kubernetes":
        return
    namespace = environment_namespace(settings, environment.id)
    api = None
    failure: Exception | None = None
    try:
        # One monotonic deadline bounds client setup, delete, every poll, and
        # client close. A stuck API call cannot delay DB cleanup indefinitely.
        async with asyncio.timeout(settings.kubernetes_namespace_deletion_timeout_seconds):
            try:
                api = await load_kubernetes_client(settings)
                await api.delete_namespace(namespace)
                while await api.namespace_exists(namespace):  # noqa: ASYNC110 - intentional polling.
                    await asyncio.sleep(settings.kubernetes_namespace_deletion_poll_seconds)
            finally:
                if api is not None:
                    await api.close()
    except Exception as exc:
        failure = exc
    if failure is not None:
        raise KubernetesNamespaceTeardownError(
            namespace=namespace, reason=str(failure)
        ) from failure


async def purge_environment(session: Session, environment: Environment) -> None:
    """Delete one environment's rows. Does not commit — the caller owns the txn."""
    service_ids = list(
        session.exec(select(Service.id).where(Service.environment_id == environment.id)).all()
    )
    # Compose-import rows point at the app/database/redis services.  Remove
    # them first so FK constraints cannot leave a PR environment half-deleted.
    imports = list(session.exec(
        select(GitHubImport).where(
            (GitHubImport.app_service_id.in_(service_ids))  # type: ignore[attr-defined]
            | (GitHubImport.postgres_service_id.in_(service_ids))  # type: ignore[attr-defined]
            | (GitHubImport.redis_service_id.in_(service_ids))  # type: ignore[attr-defined]
        )
    ).all())
    for mapping in session.exec(
        select(GitHubImportService).where(
            GitHubImportService.github_import_id.in_([item.id for item in imports])
        )
    ).all() if imports else []:
        session.delete(mapping)
    # These FKs are database-enforced without an ORM relationship, so flush
    # mapping deletes before deleting their parent imports.
    session.flush()
    for imported in imports:
        session.delete(imported)
    session.flush()
    await services.purge_services_in_environment(session, environment)
    # Sweep any domain that outlived its target — user domains attached to the
    # environment rather than to a service that was in it.
    await domains.delete_domains_for_environment(session, environment_id=environment.id)
    session.delete(environment)
    session.flush()


async def handle_pull_request(
    session: Session,
    *,
    payload: dict[str, object],
    agent: AgentClient,
    settings: Settings,
    github: GitHubAppClient,
) -> dict[str, object]:
    """Reconcile an at-least-once GitHub pull_request delivery.

    The PR number is the durable idempotency key.  Open/reopen/synchronize
    creates (or updates) the one matching environment; close/merge removes it.
    """
    action = str(payload.get("action", ""))
    pull_request = payload.get("pull_request")
    repository = payload.get("repository")
    if not isinstance(pull_request, dict) or not isinstance(repository, dict):
        return {"environments": [], "detail": "ignored malformed pull_request event"}
    number = payload.get("number")
    repo = repository.get("full_name")
    if not isinstance(number, int) or not isinstance(repo, str):
        return {"environments": [], "detail": "ignored pull_request without repository or number"}

    if action in {"closed"}:
        removed: list[str] = []
        candidates = list(
            session.exec(select(Environment).where(Environment.github_pr_number == number)).all()
        )
        for environment in candidates:
            services_in_environment = session.exec(
                select(Service).where(
                    Service.environment_id == environment.id, Service.source_repo == repo
                )
            ).first()
            if services_in_environment is None:
                continue
            await delete_environment(session, environment.id, agent=agent, settings=settings)
            removed.append(str(environment.id))
        return {"environments": removed, "detail": "destroyed" if removed else "already absent"}

    if action not in {"opened", "reopened", "synchronize"}:
        return {"environments": [], "detail": f"ignored action: {action}"}
    head = pull_request.get("head")
    if not isinstance(head, dict) or not isinstance(head.get("ref"), str):
        return {"environments": [], "detail": "ignored pull_request without a head branch"}
    branch = str(head["ref"])
    sha = str(head.get("sha") or "") or None

    source_services = list(
        session.exec(
            select(Service)
            .join(Environment, Environment.id == Service.environment_id)  # type: ignore[arg-type]
            .where(Service.source_repo == repo, Environment.is_production.is_(True))
        ).all()
    )
    created: list[str] = []
    for source_service in source_services:
        source = _require_environment(session, source_service.environment_id)
        existing = session.exec(
            select(Environment).where(
                Environment.project_id == source.project_id,
                Environment.github_pr_number == number,
            )
        ).first()
        if existing is None:
            active = session.exec(
                select(Environment).where(
                    Environment.project_id == source.project_id,
                    Environment.github_pr_number.is_not(None),
                )
            ).all()
            if len(active) >= settings.github_pr_environment_limit:
                raise RudderError(
                    "PR environment limit "
                    f"({settings.github_pr_environment_limit}) reached for this project.",
                    code="pr_environment_limit_reached",
                )
            existing = await clone_environment(
                session,
                source.id,
                EnvironmentClone(
                    name=_pr_environment_name(source.project_id, number),
                    source_branch=branch,
                    github_pr_number=number,
                ),
            )
            created.append(str(existing.id))

        # Queue only release owners. Compose children deploy as part of their
        # imported app's single release, not as independent containers.
        targets = list(
            session.exec(
                select(Service).where(
                    Service.environment_id == existing.id,
                    Service.source_repo == repo,
                )
            ).all()
        )
        for target in targets:
            if isinstance(target.build_config.get("managed_by_service_id"), str):
                continue
            duplicate = (
                sha
                and session.exec(
                    select(Deployment.id).where(
                        Deployment.service_id == target.id, Deployment.commit_sha == sha
                    )
                ).first()
            )
            if duplicate is None:
                session.add(
                    Deployment(service_id=target.id, commit_sha=sha, status=DeploymentStatus.QUEUED)
                )
        session.commit()

        # A Compose import can carry databases alongside its public app.  The
        # PR comment must point to the imported app, never whichever system
        # hostname happens to sort first (for example, postgres).
        hostname: str | None = None
        for target in targets:
            target_domains = await domains.list_domains_for_service(session, target.id)
            hostname = next(
                (domain.hostname for domain in target_domains if domain.is_system), None
            )
            if hostname is not None:
                break
        imported = session.exec(
            select(GitHubImport).where(
                GitHubImport.project_id == existing.project_id,
                GitHubImport.repository == repo,
            )
        ).first()
        if hostname and imported is not None:
            scheme = "https" if settings.tls_mode == "acme" else "http"
            # Deployment runs asynchronously.  Do not present the URL as
            # ready before its health-gated release has actually gone live.
            # The environment/deployment rows are idempotent by project/PR
            # and commit SHA, so retrying the queued notification is safe.
            await github.comment_on_pull_request(
                imported.installation_id,
                repo,
                number,
                f"Rudder PR environment deployment queued: {scheme}://{hostname}",
            )
    return {"environments": created, "detail": "created" if created else "updated"}


def _pr_environment_name(project_id: uuid.UUID, number: int) -> str:
    """Globally hostname-safe PR environment name, stable per project/PR."""
    return f"pr-{number}-{project_id.hex[:8]}"


async def _apply_environment_write(
    session: Session, *, environment: Environment, data: dict[str, object]
) -> Environment:
    renamed = "name" in data and data["name"] != environment.name

    for field, value in data.items():
        setattr(environment, field, value)

    session.add(environment)
    _flush_or_conflict(session, project_id=environment.project_id, name=environment.name)

    if renamed:
        # Every system hostname in this environment embeds the env name.
        try:
            await services.sync_system_domains_for_environment(session, environment)
        except RudderError:
            session.rollback()
            raise

    session.commit()
    session.refresh(environment)
    return environment


def _flush_or_conflict(session: Session, *, project_id: uuid.UUID, name: str) -> None:
    """uq_environment_project_name must surface as a 409, never a 500."""
    try:
        session.flush()
    except IntegrityError as err:
        session.rollback()
        raise ConflictError(
            f"an environment named '{name}' already exists in this project",
            code=ENVIRONMENT_NAME_TAKEN,
            details={"project_id": str(project_id), "name": name},
        ) from err


def _require_project(session: Session, project_id: uuid.UUID) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError(
            f"project {project_id} does not exist",
            details={"project_id": str(project_id)},
        )
    return project


def _require_environment(session: Session, environment_id: uuid.UUID) -> Environment:
    environment = session.get(Environment, environment_id)
    if environment is None:
        raise NotFoundError(
            f"environment {environment_id} does not exist",
            details={"environment_id": str(environment_id)},
        )
    return environment
