"""Traefik dynamic-config rendering (D15).

No Postgres, no Docker daemon and no running Traefik here: rows go into an
in-memory SQLite database, files are rendered into `tmp_path`, and every
assertion parses the emitted YAML rather than string-matching it.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from rudder_cp.config import Settings
from rudder_cp.models import (
    Deployment,
    DeploymentStatus,
    Domain,
    DomainTargetType,
    Environment,
    GitHubImport,
    GitHubImportService,
    Instance,
    InstanceStatus,
    Node,
    Project,
    Service,
    User,
)
from rudder_cp.services import traefik

# container_port and health_check_port are deliberately different so a test can
# actually catch routing that used the wrong one (D1).
CONTAINER_PORT = 8080
HEALTH_CHECK_PORT = 9999


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        yield db


def settings_for(tmp_path: Path, tls_mode: str = "off") -> Settings:
    return Settings(
        traefik_dynamic_dir=str(tmp_path),
        tls_mode=tls_mode,
        base_domain="localhost",
        acme_email="ops@example.com",
        docker_network="rudder",
    )


# --------------------------------------------------------------------- fixtures


def make_service(session: Session, name: str = "api") -> Service:
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="x")
    session.add(user)
    session.commit()
    project = Project(name="shop", owner_id=user.id)
    session.add(project)
    session.commit()
    environment = Environment(project_id=project.id, name="prod", is_production=True)
    session.add(environment)
    session.commit()
    service = Service(
        environment_id=environment.id,
        name=name,
        container_port=CONTAINER_PORT,
        health_check_port=HEALTH_CHECK_PORT,
    )
    session.add(service)
    session.commit()
    return service


def make_node(session: Session) -> Node:
    node = Node(hostname=f"node-{uuid.uuid4()}", ip_address="127.0.0.1")
    session.add(node)
    session.commit()
    return node


def make_deployment(
    session: Session,
    service: Service,
    status: DeploymentStatus = DeploymentStatus.LIVE,
    became_live_at: datetime | None = None,
) -> Deployment:
    deployment = Deployment(
        service_id=service.id,
        image_tag=f"localhost:5000/{service.name}:{uuid.uuid4().hex[:8]}",
        status=status,
        became_live_at=became_live_at or datetime.now(UTC),
    )
    session.add(deployment)
    session.commit()
    return deployment


def make_instance(
    session: Session,
    deployment: Deployment,
    node: Node,
    container_id: str | None,
    status: InstanceStatus = InstanceStatus.HEALTHY,
    compose_service: str | None = None,
) -> Instance:
    instance = Instance(
        deployment_id=deployment.id,
        node_id=node.id,
        container_id=container_id,
        status=status,
        compose_service=compose_service,
    )
    session.add(instance)
    session.commit()
    return instance


def make_domain(
    session: Session,
    environment_id: uuid.UUID,
    hostname: str,
    service: Service | None = None,
    deployment: Deployment | None = None,
    tls_enabled: bool = False,
) -> Domain:
    domain = Domain(
        hostname=hostname,
        environment_id=environment_id,
        target_type=(
            DomainTargetType.SERVICE if service is not None else DomainTargetType.DEPLOYMENT
        ),
        service_id=service.id if service is not None else None,
        deployment_id=deployment.id if deployment is not None else None,
        is_system=service is not None,
        tls_enabled=tls_enabled,
    )
    session.add(domain)
    session.commit()
    return domain


# ---------------------------------------------------------------------- helpers


def load(tmp_path: Path, domain: Domain) -> dict[str, Any]:
    path = tmp_path / f"{domain.id}.yml"
    assert path.is_file(), f"no router file for {domain.hostname}"
    parsed = yaml.safe_load(path.read_text())
    assert isinstance(parsed, dict)
    return parsed


def listing(tmp_path: Path) -> list[str]:
    return sorted(p.name for p in tmp_path.iterdir())


def router_of(document: dict[str, Any]) -> dict[str, Any]:
    routers = document["http"]["routers"]
    assert len(routers) == 1
    return next(iter(routers.values()))


def server_urls(document: dict[str, Any]) -> list[str]:
    services = document["http"]["services"]
    assert len(services) == 1
    load_balancer = next(iter(services.values()))["loadBalancer"]
    return [server["url"] for server in load_balancer["servers"]]


# ------------------------------------------------------------------------ tests


async def test_service_domain_routes_to_live_deployment_healthy_instances(
    session: Session, tmp_path: Path
) -> None:
    service = make_service(session)
    node = make_node(session)
    live = make_deployment(session, service)
    make_instance(session, live, node, "a" * 64)
    make_instance(session, live, node, "b" * 64)
    # Not routable: wrong state, wrong deployment, no container.
    make_instance(session, live, node, "c" * 64, status=InstanceStatus.DRAINING)
    make_instance(session, live, node, "d" * 64, status=InstanceStatus.STARTING)
    make_instance(session, live, node, None, status=InstanceStatus.HEALTHY)
    old = make_deployment(session, service, status=DeploymentStatus.SUPERSEDED)
    make_instance(session, old, node, "e" * 64)

    domain = make_domain(session, service.environment_id, "api.prod.localhost", service=service)
    await traefik.render_all(session, settings_for(tmp_path))

    document = load(tmp_path, domain)
    assert server_urls(document) == [
        f"http://{'a' * 12}:{CONTAINER_PORT}/",
        f"http://{'b' * 12}:{CONTAINER_PORT}/",
    ]
    assert router_of(document)["rule"] == "Host(`api.prod.localhost`)"


async def test_public_compose_child_routes_to_its_own_container(
    session: Session, tmp_path: Path
) -> None:
    """A reviewed Grafana URL must not accidentally point at the web app."""
    app = make_service(session, "api")
    grafana = Service(
        environment_id=app.environment_id,
        name="grafana",
        container_port=3000,
        build_config={"managed_by_service_id": str(app.id), "compose_service": "grafana"},
    )
    session.add(grafana)
    session.commit()
    imported = GitHubImport(
        installation_id=42,
        repository="acme/api",
        branch="main",
        compose_source="repository",
        compose_manifest="services: {}",
        compose_project_name="rudder-api",
        project_id=session.get(Environment, app.environment_id).project_id,
        app_service_id=app.id,
    )
    session.add(imported)
    session.commit()
    session.add(
        GitHubImportService(
            github_import_id=imported.id,
            service_id=grafana.id,
            compose_service="grafana",
            role="observability",
            is_public=True,
            container_id="g" * 64,
        )
    )
    session.commit()
    node = make_node(session)
    live = make_deployment(session, app)
    make_instance(session, live, node, "a" * 64)
    make_instance(session, live, node, "g" * 64)
    domain = make_domain(
        session, grafana.environment_id, "grafana.prod.localhost", service=grafana
    )

    await traefik.render_all(session, settings_for(tmp_path))

    assert server_urls(load(tmp_path, domain)) == [f"http://{'g' * 12}:3000/"]


async def test_compose_app_domain_routes_only_to_its_app_container(
    session: Session, tmp_path: Path
) -> None:
    """The app domain must never round-robin through Compose add-ons."""
    app = make_service(session, "api")
    postgres = Service(
        environment_id=app.environment_id,
        name="postgres",
        container_port=5432,
        build_config={"managed_by_service_id": str(app.id), "compose_service": "postgres"},
    )
    redis = Service(
        environment_id=app.environment_id,
        name="redis",
        container_port=6379,
        build_config={"managed_by_service_id": str(app.id), "compose_service": "redis"},
    )
    session.add_all([postgres, redis])
    session.commit()

    imported = GitHubImport(
        installation_id=42,
        repository="acme/api",
        branch="main",
        compose_source="repository",
        compose_manifest="services: {}",
        compose_project_name="rudder-api",
        project_id=session.get(Environment, app.environment_id).project_id,
        app_service_id=app.id,
    )
    session.add(imported)
    session.commit()
    session.add_all(
        [
            GitHubImportService(
                github_import_id=imported.id,
                service_id=app.id,
                compose_service="app",
                role="application",
                is_public=True,
                container_id="a" * 64,
            ),
            GitHubImportService(
                github_import_id=imported.id,
                service_id=postgres.id,
                compose_service="postgres",
                role="database",
                is_public=False,
                container_id="p" * 64,
            ),
            GitHubImportService(
                github_import_id=imported.id,
                service_id=redis.id,
                compose_service="redis",
                role="cache",
                is_public=False,
                container_id="r" * 64,
            ),
        ]
    )
    session.commit()
    node = make_node(session)
    live = make_deployment(session, app)
    make_instance(session, live, node, "a" * 64)
    make_instance(session, live, node, "p" * 64)
    make_instance(session, live, node, "r" * 64)
    domain = make_domain(session, app.environment_id, "api.prod.localhost", service=app)

    await traefik.render_all(session, settings_for(tmp_path))

    assert server_urls(load(tmp_path, domain)) == [f"http://{'a' * 12}:{CONTAINER_PORT}/"]


async def test_pinned_compose_app_domain_routes_only_to_its_app_container(
    session: Session, tmp_path: Path
) -> None:
    """Rollback domains must retain the same add-on isolation as live domains."""
    app = make_service(session, "api")
    postgres = Service(
        environment_id=app.environment_id,
        name="postgres",
        container_port=5432,
        build_config={"managed_by_service_id": str(app.id), "compose_service": "postgres"},
    )
    session.add(postgres)
    session.commit()
    imported = GitHubImport(
        installation_id=42,
        repository="acme/api",
        branch="main",
        compose_source="repository",
        compose_manifest="services: {}",
        compose_project_name="rudder-api",
        project_id=session.get(Environment, app.environment_id).project_id,
        app_service_id=app.id,
    )
    session.add(imported)
    session.commit()
    session.add_all(
        [
            GitHubImportService(
                github_import_id=imported.id,
                service_id=app.id,
                compose_service="app",
                role="application",
                is_public=True,
                container_id="a" * 64,
            ),
            GitHubImportService(
                github_import_id=imported.id,
                service_id=postgres.id,
                compose_service="postgres",
                role="database",
                is_public=False,
                container_id="p" * 64,
            ),
        ]
    )
    session.commit()
    node = make_node(session)
    deployment = make_deployment(session, app)
    make_instance(session, deployment, node, "a" * 64)
    make_instance(session, deployment, node, "p" * 64)
    domain = make_domain(
        session,
        app.environment_id,
        "rollback-api.prod.localhost",
        deployment=deployment,
    )

    await traefik.render_all(session, settings_for(tmp_path))

    assert server_urls(load(tmp_path, domain)) == [f"http://{'a' * 12}:{CONTAINER_PORT}/"]


async def test_restored_compose_release_uses_its_own_historical_app_container(
    session: Session, tmp_path: Path
) -> None:
    """A restore must not route an old release through the newer app container."""
    app = make_service(session, "api")
    imported = GitHubImport(
        installation_id=42,
        repository="acme/api",
        branch="main",
        compose_source="repository",
        compose_manifest="services: {}",
        compose_project_name="rudder-api",
        project_id=session.get(Environment, app.environment_id).project_id,
        app_service_id=app.id,
    )
    session.add(imported)
    session.commit()
    # This mutable projection points at the newer release, as it does after a
    # normal deployment. Historical routing must use Instance.compose_service.
    session.add(
        GitHubImportService(
            github_import_id=imported.id,
            service_id=app.id,
            compose_service="app",
            role="application",
            is_public=True,
            container_id="n" * 64,
        )
    )
    session.commit()
    node = make_node(session)
    restored = make_deployment(session, app)
    newer = make_deployment(session, app, status=DeploymentStatus.SUPERSEDED)
    make_instance(session, restored, node, "o" * 64, compose_service="app")
    make_instance(session, newer, node, "n" * 64, compose_service="app")
    domain = make_domain(session, app.environment_id, "api.prod.localhost", service=app)

    await traefik.render_all(session, settings_for(tmp_path))

    assert server_urls(load(tmp_path, domain)) == [f"http://{'o' * 12}:{CONTAINER_PORT}/"]


async def test_service_domain_follows_a_newer_live_deployment(
    session: Session, tmp_path: Path
) -> None:
    service = make_service(session)
    node = make_node(session)
    settings = settings_for(tmp_path)

    now = datetime.now(UTC)
    first = make_deployment(session, service, became_live_at=now)
    make_instance(session, first, node, "1" * 64)
    domain = make_domain(session, service.environment_id, "api.prod.localhost", service=service)
    await traefik.render_all(session, settings)
    assert server_urls(load(tmp_path, domain)) == [f"http://{'1' * 12}:{CONTAINER_PORT}/"]

    # A newer deploy goes live; the old one is superseded and drains (D11/D10).
    second = make_deployment(session, service, became_live_at=now + timedelta(seconds=30))
    make_instance(session, second, node, "2" * 64)
    first.status = DeploymentStatus.SUPERSEDED
    session.add(first)
    session.commit()

    await traefik.render_all(session, settings)
    assert server_urls(load(tmp_path, domain)) == [f"http://{'2' * 12}:{CONTAINER_PORT}/"]


async def test_deployment_domain_stays_pinned_after_a_newer_deployment_goes_live(
    session: Session, tmp_path: Path
) -> None:
    """The rollback property. A deployment-targeted Domain is Vercel semantics:
    pinned to one immutable build forever, which is what makes rollback an
    UPDATE on a Domain row instead of a rebuild."""
    service = make_service(session)
    node = make_node(session)
    settings = settings_for(tmp_path)

    now = datetime.now(UTC)
    pinned = make_deployment(session, service, became_live_at=now)
    make_instance(session, pinned, node, "1" * 64)

    pinned_domain = make_domain(
        session, service.environment_id, "abc123-api.localhost", deployment=pinned
    )
    following_domain = make_domain(
        session, service.environment_id, "api.prod.localhost", service=service
    )

    newer = make_deployment(session, service, became_live_at=now + timedelta(seconds=30))
    make_instance(session, newer, node, "2" * 64)
    pinned.status = DeploymentStatus.SUPERSEDED
    session.add(pinned)
    session.commit()

    await traefik.render_all(session, settings)

    # The pinned domain still serves its own (now superseded) deployment...
    assert server_urls(load(tmp_path, pinned_domain)) == [f"http://{'1' * 12}:{CONTAINER_PORT}/"]
    # ...while the service-targeted domain moved to the new live one.
    assert server_urls(load(tmp_path, following_domain)) == [f"http://{'2' * 12}:{CONTAINER_PORT}/"]

    # Rollback: repoint the service domain at the old deployment. One UPDATE.
    following_domain.target_type = DomainTargetType.DEPLOYMENT
    following_domain.service_id = None
    following_domain.deployment_id = pinned.id
    session.add(following_domain)
    session.commit()

    await traefik.render_all(session, settings)
    assert server_urls(load(tmp_path, following_domain)) == [f"http://{'1' * 12}:{CONTAINER_PORT}/"]


async def test_domain_with_no_healthy_instances_keeps_its_router_with_no_backends(
    session: Session, tmp_path: Path
) -> None:
    """Router present, server list empty. Traefik answers 503, not 404 — the
    hostname exists, it just has nothing behind it right now."""
    service = make_service(session)
    node = make_node(session)
    deployment = make_deployment(session, service)
    make_instance(session, deployment, node, "a" * 64, status=InstanceStatus.UNHEALTHY)
    domain = make_domain(session, service.environment_id, "api.prod.localhost", service=service)

    await traefik.render_all(session, settings_for(tmp_path))

    document = load(tmp_path, domain)
    assert server_urls(document) == []
    assert router_of(document)["rule"] == "Host(`api.prod.localhost`)"


async def test_service_with_no_deployment_at_all_still_gets_a_router(
    session: Session, tmp_path: Path
) -> None:
    service = make_service(session)
    domain = make_domain(session, service.environment_id, "api.prod.localhost", service=service)

    await traefik.render_all(session, settings_for(tmp_path))

    assert server_urls(load(tmp_path, domain)) == []


async def test_rendering_twice_is_byte_identical_and_does_not_touch_files(
    session: Session, tmp_path: Path
) -> None:
    service = make_service(session)
    node = make_node(session)
    deployment = make_deployment(session, service)
    make_instance(session, deployment, node, "a" * 64)
    domain = make_domain(session, service.environment_id, "api.prod.localhost", service=service)
    settings = settings_for(tmp_path)

    await traefik.render_all(session, settings)
    path = tmp_path / f"{domain.id}.yml"
    first_bytes = path.read_bytes()
    first_mtime = path.stat().st_mtime_ns

    await traefik.render_all(session, settings)
    assert path.read_bytes() == first_bytes
    # Unchanged content must not be rewritten, or Traefik reloads for nothing.
    assert path.stat().st_mtime_ns == first_mtime
    # And no temp files are left behind.
    assert listing(tmp_path) == [f"{domain.id}.yml"]


async def test_deleted_domain_file_is_removed_on_the_next_render(
    session: Session, tmp_path: Path
) -> None:
    service = make_service(session)
    settings = settings_for(tmp_path)
    keep = make_domain(session, service.environment_id, "api.prod.localhost", service=service)
    doomed = make_domain(session, service.environment_id, "old.prod.localhost", service=service)

    await traefik.render_all(session, settings)
    assert (tmp_path / f"{doomed.id}.yml").is_file()

    session.delete(doomed)
    session.commit()
    await traefik.render_all(session, settings)

    assert not (tmp_path / f"{doomed.id}.yml").exists()
    assert (tmp_path / f"{keep.id}.yml").is_file()


async def test_unrelated_files_in_the_directory_survive(session: Session, tmp_path: Path) -> None:
    service = make_service(session)
    domain = make_domain(session, service.environment_id, "api.prod.localhost", service=service)

    (tmp_path / ".gitkeep").write_text("")
    (tmp_path / "middlewares.yml").write_text("http:\n  middlewares: {}\n")
    (tmp_path / "notes.txt").write_text("hand written")
    stranger = tmp_path / "not-a-uuid.yml"
    stranger.write_text("http: {}\n")

    await traefik.render_all(session, settings_for(tmp_path))

    assert (tmp_path / ".gitkeep").exists()
    assert (tmp_path / "middlewares.yml").exists()
    assert (tmp_path / "notes.txt").exists()
    assert stranger.exists()
    assert (tmp_path / f"{domain.id}.yml").is_file()


async def test_stale_temp_file_from_a_crashed_render_is_cleaned_up(
    session: Session, tmp_path: Path
) -> None:
    service = make_service(session)
    make_domain(session, service.environment_id, "api.prod.localhost", service=service)
    orphan = tmp_path / f".{uuid.uuid4()}.yml.tmp"
    orphan.write_text("half written")

    await traefik.render_all(session, settings_for(tmp_path))

    assert not orphan.exists()


async def test_tls_mode_off_emits_a_plain_http_router(session: Session, tmp_path: Path) -> None:
    service = make_service(session)
    domain = make_domain(
        session, service.environment_id, "api.prod.localhost", service=service, tls_enabled=True
    )

    await traefik.render_all(session, settings_for(tmp_path, tls_mode="off"))

    router = router_of(load(tmp_path, domain))
    assert "tls" not in router
    assert router["entryPoints"] == ["web"]


async def test_tls_mode_acme_emits_the_tls_block(session: Session, tmp_path: Path) -> None:
    service = make_service(session)
    domain = make_domain(
        session, service.environment_id, "api.rudder.dev", service=service, tls_enabled=True
    )

    await traefik.render_all(session, settings_for(tmp_path, tls_mode="acme"))

    router = router_of(load(tmp_path, domain))
    assert router["entryPoints"] == ["websecure"]
    assert router["tls"]["certResolver"] == "rudder"
    assert router["tls"]["domains"] == [{"main": "api.rudder.dev"}]


async def test_acme_respects_a_domain_that_opts_out_of_tls(
    session: Session, tmp_path: Path
) -> None:
    service = make_service(session)
    domain = make_domain(
        session, service.environment_id, "api.rudder.dev", service=service, tls_enabled=False
    )

    await traefik.render_all(session, settings_for(tmp_path, tls_mode="acme"))

    router = router_of(load(tmp_path, domain))
    assert "tls" not in router
    assert router["entryPoints"] == ["web"]


async def test_routing_uses_container_port_not_health_check_port(
    session: Session, tmp_path: Path
) -> None:
    service = make_service(session)
    assert service.container_port != service.health_check_port
    node = make_node(session)
    deployment = make_deployment(session, service)
    make_instance(session, deployment, node, "a" * 64)
    domain = make_domain(session, service.environment_id, "api.prod.localhost", service=service)

    await traefik.render_all(session, settings_for(tmp_path))

    urls = server_urls(load(tmp_path, domain))
    assert urls == [f"http://{'a' * 12}:{CONTAINER_PORT}/"]
    assert str(HEALTH_CHECK_PORT) not in (tmp_path / f"{domain.id}.yml").read_text()


async def test_router_and_service_names_are_unique_per_domain(
    session: Session, tmp_path: Path
) -> None:
    service = make_service(session)
    first = make_domain(session, service.environment_id, "a.prod.localhost", service=service)
    second = make_domain(session, service.environment_id, "b.prod.localhost", service=service)

    await traefik.render_all(session, settings_for(tmp_path))

    names = set()
    for domain in (first, second):
        document = load(tmp_path, domain)
        names |= set(document["http"]["routers"])
        names |= set(document["http"]["services"])
    assert names == {f"rudder-{first.id}", f"rudder-{second.id}"}


async def test_concurrent_renders_converge(session: Session, tmp_path: Path) -> None:
    service = make_service(session)
    node = make_node(session)
    deployment = make_deployment(session, service)
    make_instance(session, deployment, node, "a" * 64)
    domain = make_domain(session, service.environment_id, "api.prod.localhost", service=service)
    settings = settings_for(tmp_path)

    await asyncio.gather(*(traefik.render_all(session, settings) for _ in range(5)))

    assert server_urls(load(tmp_path, domain)) == [f"http://{'a' * 12}:{CONTAINER_PORT}/"]
    assert listing(tmp_path) == [f"{domain.id}.yml"]
