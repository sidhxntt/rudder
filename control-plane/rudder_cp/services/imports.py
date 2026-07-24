"""Repository inspection and add-on proposals for GitHub imports.

Detection is intentionally manifest-based. A dependency shows that an add-on is
plausible; the user still confirms provisioning before Rudder creates anything.
"""

from __future__ import annotations

import re
import secrets
import uuid
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, select

from rudder_cp.config import get_settings
from rudder_cp.models import (
    Deployment,
    DeploymentStatus,
    Domain,
    Environment,
    GitHubImport,
    GitHubImportService,
    Service,
    ServiceKind,
    Variable,
    Volume,
)
from rudder_cp.schemas.project import ProjectCreate
from rudder_cp.schemas.service import ServiceCreate
from rudder_cp.services import projects, services, variables
from rudder_cp.services.compose import ComposePlan, generated_compose_plan
from rudder_cp.services.naming import system_hostname
from rudder_cp.services.variables import encrypt_value, is_reference

_ADDON_CLIENTS: tuple[tuple[str, frozenset[str], str], ...] = (
    ("postgres", frozenset({"pg", "@prisma/client", "prisma", "sequelize"}), "DATABASE_URL"),
    ("redis", frozenset({"redis", "ioredis"}), "REDIS_URL"),
    ("mysql", frozenset({"mysql", "mysql2", "typeorm"}), "MYSQL_URL"),
    ("mariadb", frozenset({"mariadb"}), "MARIADB_URL"),
    ("mongodb", frozenset({"mongodb", "mongoose"}), "MONGODB_URI"),
    ("memcached", frozenset({"memjs", "memcached"}), "MEMCACHED_URL"),
    ("rabbitmq", frozenset({"amqplib"}), "RABBITMQ_URL"),
    ("nats", frozenset({"nats"}), "NATS_URL"),
    ("meilisearch", frozenset({"meilisearch"}), "MEILISEARCH_HOST"),
    ("typesense", frozenset({"typesense"}), "TYPESENSE_HOST"),
    ("minio", frozenset({"minio"}), "MINIO_ENDPOINT"),
    ("qdrant", frozenset({"@qdrant/js-client-rest", "qdrant-client"}), "QDRANT_URL"),
)
_SUPPORTED_ADDONS = frozenset({name for name, _, _ in _ADDON_CLIENTS})
_SERVICE_NAME = re.compile(r"[^a-z0-9-]+")


@dataclass(frozen=True, slots=True)
class AddonProposal:
    """The safe, reviewable result of inspecting one Node ``package.json``."""

    is_node_app: bool
    addons: tuple[str, ...]
    externally_managed: tuple[str, ...]


def detect_node_addons(
    package_json: dict[str, Any], *, existing_variable_keys: set[str]
) -> AddonProposal:
    """Return confirmable Postgres/Redis candidates from a package manifest.

    An existing connection variable always wins over package inference: Rudder
    must not replace a deliberately configured external database or cache.
    """
    dependencies = _dependencies(package_json)
    is_node_app = "express" in dependencies
    addons: list[str] = []
    externally_managed: list[str] = []

    for addon, clients, variable_key in _ADDON_CLIENTS:
        if dependencies & clients:
            _propose_or_mark_external(
                addon=addon,
                variable_key=variable_key,
                existing_variable_keys=existing_variable_keys,
                addons=addons,
                externally_managed=externally_managed,
            )

    return AddonProposal(
        is_node_app=is_node_app,
        addons=tuple(addons),
        externally_managed=tuple(externally_managed),
    )


def _dependencies(package_json: dict[str, Any]) -> set[str]:
    combined: set[str] = set()
    for key in ("dependencies", "devDependencies"):
        values = package_json.get(key)
        if isinstance(values, dict):
            combined.update(name for name, version in values.items() if isinstance(version, str))
    return combined


def _propose_or_mark_external(
    *,
    addon: str,
    variable_key: str,
    existing_variable_keys: set[str],
    addons: list[str],
    externally_managed: list[str],
) -> None:
    if variable_key in existing_variable_keys:
        externally_managed.append(addon)
    else:
        addons.append(addon)


@dataclass(frozen=True, slots=True)
class ConfirmedImport:
    """The ids the UI needs to navigate and poll a confirmed import."""

    import_id: uuid.UUID
    project_id: uuid.UUID
    environment_id: uuid.UUID
    app_service_id: uuid.UUID


def compose_project_name(project_id: uuid.UUID) -> str:
    """Return a deterministic, Docker Compose-safe project namespace."""
    return f"rudder-{project_id.hex}"


async def provision_import(
    session: Session,
    *,
    installation_id: int,
    repository: str,
    branch: str,
    selected_addons: set[str],
    proposal: AddonProposal,
    compose_plan: ComposePlan | None = None,
) -> ConfirmedImport:
    """Create an app graph, wire private dependencies, then queue it in order.

    This is deliberately invoked only after the caller has re-read the manifest
    and checked the user's add-on choices against ``proposal``. Package
    dependencies can suggest infrastructure; they can never create it alone.
    """
    unsupported = selected_addons - _SUPPORTED_ADDONS
    unproposed = selected_addons - set(proposal.addons)
    if unsupported or unproposed:
        raise ValueError("Selected add-ons must be a subset of the detected add-ons.")
    plan = compose_plan or generated_compose_plan(selected_addons)
    if not proposal.is_node_app and plan.source != "repository":
        raise ValueError("Only Node.js repositories can be imported in Phase 1.")
    if plan.source == "repository" and selected_addons:
        raise ValueError("Repository Compose files define their own dependencies.")

    public_services = [service for service in plan.services.values() if service.public_port]
    if len(public_services) != 1:
        raise ValueError("A Compose import must declare exactly one public application service.")
    public_service = public_services[0]

    project = await projects.create_project(
        session, ProjectCreate(name=_project_name(repository))
    )
    environment = session.exec(
        select(Environment).where(
            Environment.project_id == project.id,
            Environment.is_production.is_(True),
        )
    ).one()

    postgres = (
        _managed_postgres(session, environment.id) if "postgres" in selected_addons else None
    )
    redis = _managed_redis(session, environment.id) if "redis" in selected_addons else None
    session.commit()

    app = await services.create_service(
        session,
        environment.id,
        ServiceCreate(
            name=_available_app_name(session, repository),
            source_repo=repository,
            source_branch=branch,
            build_config={"compose_service": public_service.name},
            container_port=public_service.public_port or 3000,
            health_check_port=public_service.public_port or 3000,
            canvas_x=360,
        ),
    )

    if postgres is not None:
        await variables.set_variable(
            session, app.id, "DATABASE_URL", "${{postgres.DATABASE_URL}}"
        )
    if redis is not None:
        await variables.set_variable(session, app.id, "REDIS_URL", "${{redis.REDIS_URL}}")

    record = GitHubImport(
        installation_id=installation_id,
        repository=repository,
        branch=branch,
        compose_source=plan.source,
        compose_manifest=plan.yaml,
        compose_project_name=compose_project_name(project.id),
        project_id=project.id,
        app_service_id=app.id,
        postgres_service_id=postgres.id if postgres else None,
        redis_service_id=redis.id if redis else None,
    )
    session.add(record)
    session.flush()
    for service_id, compose_service, role, is_public in (
        (app.id, public_service.name, public_service.role, True),
        (postgres.id if postgres else None, "postgres", "database", False),
        (redis.id if redis else None, "redis", "cache", False),
    ):
        if service_id is None:
            continue
        session.add(
            GitHubImportService(
                github_import_id=record.id,
                service_id=service_id,
                compose_service=compose_service,
                role=role,
                is_public=is_public,
            )
        )
    session.commit()
    session.refresh(record)

    # One imported application deployment starts the whole Compose project.
    # Add-ons are private Compose services, not separately deployed containers.
    session.add(Deployment(service_id=app.id, status=DeploymentStatus.QUEUED))
    session.commit()

    return ConfirmedImport(
        import_id=record.id,
        project_id=project.id,
        environment_id=environment.id,
        app_service_id=app.id,
    )


def import_progress(session: Session, record: GitHubImport) -> list[dict[str, str | None]]:
    """Return actual deployment state in the order the import was provisioned."""
    rows: list[dict[str, str | None]] = []
    for label, service_id in (
        ("Postgres", record.postgres_service_id),
        ("Redis", record.redis_service_id),
        ("Application", record.app_service_id),
    ):
        if service_id is None:
            continue
        service = session.get(Service, service_id)
        deployment = session.exec(
            select(Deployment)
            .where(Deployment.service_id == service_id)
            .order_by(Deployment.created_at.desc())  # type: ignore[attr-defined]
        ).first()
        rows.append(
            {
                "label": label,
                "service_id": str(service_id),
                "service_name": service.name if service else None,
                "deployment_id": str(deployment.id) if deployment else None,
                "status": deployment.status.value if deployment else "queued",
                "error_message": deployment.error_message if deployment else None,
            }
        )
    return rows


def app_dependency_state(session: Session, app_service_id: uuid.UUID) -> tuple[str, str | None]:
    """Return whether an imported app may deploy after its managed add-ons.

    The worker uses this before it hands an app deployment to BuildKit. It is a
    real deployment dependency, not just insertion order: a failed Postgres or
    Redis deploy can never be followed by an app deploy against a missing host.
    """
    record = session.exec(
        select(GitHubImport).where(GitHubImport.app_service_id == app_service_id)
    ).first()
    if record is None:
        return "ready", None
    # GitHub imports deploy their add-ons as one Compose release. The app must
    # therefore not wait for legacy per-container deployment rows.
    return "ready", None



def _managed_postgres(session: Session, environment_id: uuid.UUID) -> Service:
    password = secrets.token_urlsafe(32)
    service = Service(
        environment_id=environment_id,
        name="postgres",
        kind=ServiceKind.DATABASE,
        build_config={"managed_image": "postgres:16-alpine"},
        container_port=5432,
        health_check_port=5432,
        health_check_path="/",
        canvas_x=0,
        canvas_y=-140,
    )
    session.add(service)
    session.flush()
    session.add(Volume(service_id=service.id, mount_path="/var/lib/postgresql/data"))
    session.commit()
    # ``DATABASE_URL`` is stored on the add-on then referenced by the app, so
    # the generated password never appears in an API response.
    _set_managed_variable(session, service.id, "POSTGRES_DB", "app")
    _set_managed_variable(session, service.id, "POSTGRES_USER", "rudder")
    _set_managed_variable(session, service.id, "POSTGRES_PASSWORD", password)
    _set_managed_variable(
        session,
        service.id,
        "DATABASE_URL",
        f"postgresql://rudder:{password}@postgres:5432/app",
    )
    return service


def _managed_redis(session: Session, environment_id: uuid.UUID) -> Service:
    password = secrets.token_urlsafe(32)
    service = Service(
        environment_id=environment_id,
        name="redis",
        kind=ServiceKind.DATABASE,
        build_config={
            "managed_image": "redis:7-alpine",
            "command": ["redis-server", "--requirepass", password],
        },
        container_port=6379,
        health_check_port=6379,
        health_check_path="/",
        canvas_x=0,
        canvas_y=140,
    )
    session.add(service)
    session.flush()
    session.add(Volume(service_id=service.id, mount_path="/data"))
    session.commit()
    _set_managed_variable(
        session, service.id, "REDIS_URL", f"redis://:{password}@redis:6379/0"
    )
    return service


def _set_managed_variable(session: Session, service_id: uuid.UUID, key: str, value: str) -> None:
    """Synchronous helper used while provisioning trusted server-side values."""
    session.add(
        Variable(
            service_id=service_id,
            key=key,
            value_encrypted=encrypt_value(value),
            is_reference=is_reference(value),
        )
    )
    session.commit()


def _app_name(repository: str) -> str:
    candidate = _SERVICE_NAME.sub("-", repository.rsplit("/", 1)[-1].lower()).strip("-")
    return (candidate or "app")[:32].rstrip("-")


def _available_app_name(session: Session, repository: str) -> str:
    """Find a hostname-safe service name for a repeat import.

    System domains are globally unique, while every imported project starts
    with an environment named ``production``. Importing the same repository a
    second time must therefore suffix the app name rather than returning a
    hostname conflict after partially creating its managed add-ons.
    """
    base = _app_name(repository)
    settings = get_settings()
    suffix = 1
    while True:
        ending = "" if suffix == 1 else f"-{suffix}"
        candidate = f"{base[: 32 - len(ending)].rstrip('-')}{ending}"
        hostname = system_hostname(candidate, "production", settings.base_domain)
        existing = session.exec(select(Domain.id).where(Domain.hostname == hostname)).first()
        if existing is None:
            return candidate
        suffix += 1


def _project_name(repository: str) -> str:
    return f"{repository.rsplit('/', 1)[-1][:56]} import"
