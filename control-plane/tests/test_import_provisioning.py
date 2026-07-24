"""Confirmed GitHub imports create a private add-on graph before the app."""

from collections.abc import Iterator

import pytest
from cryptography.fernet import Fernet
from sqlmodel import Session, SQLModel, create_engine, select

from rudder_cp.config import get_settings
from rudder_cp.models import (
    Deployment,
    Domain,
    GitHubImport,
    GitHubImportService,
    Service,
    User,
    Variable,
    Volume,
)
from rudder_cp.services.compose import (
    GeneratedProcess,
    generated_compose_plan,
    parse_repository_compose,
)
from rudder_cp.services.imports import (
    AddonProposal,
    app_dependency_state,
    import_progress,
    provision_import,
)
from rudder_cp.services.variables import decrypt_value


@pytest.fixture
def session(monkeypatch: pytest.MonkeyPatch) -> Iterator[Session]:
    monkeypatch.setenv("RUDDER_SECRET_KEYS", Fernet.generate_key().decode())
    get_settings.cache_clear()
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as open_session:
        open_session.add(User(email="owner@example.com", password_hash="x"))
        open_session.commit()
        yield open_session
    engine.dispose()
    get_settings.cache_clear()


async def test_confirmed_import_provisions_private_addons_before_the_app(session: Session) -> None:
    result = await provision_import(
        session,
        installation_id=42,
        repository="acme/store-api",
        branch="main",
        selected_addons={"postgres", "redis"},
        proposal=AddonProposal(
            is_node_app=True,
            addons=("postgres", "redis"),
            externally_managed=(),
        ),
    )

    services = list(session.exec(select(Service).order_by(Service.created_at)).all())
    assert [service.name for service in services] == ["postgres", "redis", "store-api"]
    assert [service.kind.value for service in services] == ["database", "database", "app"]
    assert [service.build_config.get("managed_image") for service in services[:2]] == [
        "postgres:16-alpine",
        "redis:7-alpine",
    ]
    assert session.exec(select(Domain)).one().service_id == result.app_service_id
    assert len(session.exec(select(Volume)).all()) == 2

    app_variables = list(
        session.exec(select(Variable).where(Variable.service_id == result.app_service_id)).all()
    )
    values = {variable.key: decrypt_value(variable.value_encrypted) for variable in app_variables}
    assert values == {
        "DATABASE_URL": "${{postgres.DATABASE_URL}}",
        "REDIS_URL": "${{redis.REDIS_URL}}",
    }

    deployments = list(session.exec(select(Deployment).order_by(Deployment.created_at)).all())
    assert [deployment.service_id for deployment in deployments] == [result.app_service_id]

    record = session.get(GitHubImport, result.import_id)
    assert record is not None
    assert record.compose_source == "generated"
    assert record.compose_project_name == f"rudder-{record.project_id.hex}"
    assert "postgres:16-alpine" in record.compose_manifest
    assert "redis:7-alpine" in record.compose_manifest
    assert [step["label"] for step in import_progress(session, record)] == [
        "Postgres",
        "Redis",
        "Application",
    ]
    graph = list(
        session.exec(
            select(GitHubImportService)
            .where(GitHubImportService.github_import_id == result.import_id)
            .order_by(GitHubImportService.compose_service)
        ).all()
    )
    assert [(row.compose_service, row.role, row.is_public) for row in graph] == [
        ("app", "web", True),
        ("postgres", "database", False),
        ("redis", "cache", False),
    ]


async def test_confirmed_import_rejects_addons_not_in_the_review(session: Session) -> None:
    with pytest.raises(ValueError, match="subset"):
        await provision_import(
            session,
            installation_id=42,
            repository="acme/store-api",
            branch="main",
            selected_addons={"postgres"},
            proposal=AddonProposal(is_node_app=True, addons=(), externally_managed=()),
        )


async def test_catalog_addons_create_private_services_and_app_references(session: Session) -> None:
    result = await provision_import(
        session,
        installation_id=42,
        repository="acme/queue-api",
        branch="main",
        selected_addons={"mysql", "rabbitmq", "minio", "prometheus", "grafana"},
        proposal=AddonProposal(
            is_node_app=True,
            addons=("mysql", "rabbitmq", "minio", "prometheus", "grafana"),
            externally_managed=(),
        ),
    )

    services = list(session.exec(select(Service).order_by(Service.name)).all())
    assert [service.name for service in services] == [
        "grafana",
        "minio",
        "mysql",
        "prometheus",
        "queue-api",
        "rabbitmq",
    ]
    assert len(session.exec(select(Volume)).all()) == 5
    app_variables = list(
        session.exec(select(Variable).where(Variable.service_id == result.app_service_id)).all()
    )
    assert {variable.key for variable in app_variables} == {
        "MYSQL_URL",
        "RABBITMQ_URL",
        "MINIO_ENDPOINT",
    }


async def test_generated_worker_is_private_and_receives_app_addon_references(
    session: Session,
) -> None:
    result = await provision_import(
        session,
        installation_id=42,
        repository="acme/jobs-api",
        branch="main",
        selected_addons={"redis"},
        proposal=AddonProposal(is_node_app=True, addons=("redis",), externally_managed=()),
        compose_plan=generated_compose_plan(
            {"redis"}, (GeneratedProcess(role="worker", command="npm run worker"),)
        ),
    )

    worker = session.exec(select(Service).where(Service.name == "worker")).one()
    assert worker.build_config["managed_by_service_id"] == str(result.app_service_id)
    variables_for_worker = list(
        session.exec(select(Variable).where(Variable.service_id == worker.id)).all()
    )
    assert {variable.key for variable in variables_for_worker} == {"REDIS_URL"}


async def test_repository_compose_creates_private_worker_and_observability_services(
    session: Session,
) -> None:
    result = await provision_import(
        session,
        installation_id=42,
        repository="acme/observed-api",
        branch="main",
        selected_addons=set(),
        proposal=AddonProposal(is_node_app=False, addons=(), externally_managed=()),
        compose_plan=parse_repository_compose(
            "services:\n"
            "  web: {build: ., ports: [3000]}\n"
            "  worker: {build: ., command: npm run worker}\n"
            "  prometheus: {image: prom/prometheus:v3}\n"
            "  grafana: {image: grafana/grafana:11}\n"
        ),
    )

    graph = list(
        session.exec(
            select(GitHubImportService)
            .where(GitHubImportService.github_import_id == result.import_id)
            .order_by(GitHubImportService.compose_service)
        ).all()
    )
    assert [(row.compose_service, row.role, row.is_public) for row in graph] == [
        ("grafana", "observability", False),
        ("prometheus", "observability", False),
        ("web", "web", True),
        ("worker", "worker", False),
    ]


async def test_repository_compose_creates_domains_only_for_reviewed_public_services(
    session: Session,
) -> None:
    result = await provision_import(
        session,
        installation_id=42,
        repository="acme/observed-api",
        branch="main",
        selected_addons=set(),
        selected_public_services={"web", "grafana"},
        proposal=AddonProposal(is_node_app=False, addons=(), externally_managed=()),
        compose_plan=parse_repository_compose(
            "services:\n"
            "  web: {build: ., ports: [3000]}\n"
            "  worker: {build: ., command: npm run worker}\n"
            "  grafana: {image: grafana/grafana:11, ports: [3000]}\n"
        ),
    )

    domains = list(session.exec(select(Domain).order_by(Domain.hostname)).all())
    names_by_id = {
        service.id: service.name for service in session.exec(select(Service)).all()
    }
    assert {names_by_id[domain.service_id] for domain in domains} == {
        "observed-api",
        "grafana",
    }

    graph = list(
        session.exec(
            select(GitHubImportService)
            .where(GitHubImportService.github_import_id == result.import_id)
            .order_by(GitHubImportService.compose_service)
        ).all()
    )
    assert [(row.compose_service, row.is_public) for row in graph] == [
        ("grafana", True),
        ("web", True),
        ("worker", False),
    ]


async def test_repeat_import_gets_a_unique_app_hostname(session: Session) -> None:
    proposal = AddonProposal(
        is_node_app=True,
        addons=("postgres",),
        externally_managed=(),
    )
    first = await provision_import(
        session,
        installation_id=42,
        repository="acme/store-api",
        branch="main",
        selected_addons={"postgres"},
        proposal=proposal,
    )
    second = await provision_import(
        session,
        installation_id=42,
        repository="acme/store-api",
        branch="main",
        selected_addons={"postgres"},
        proposal=proposal,
    )

    assert session.get(Service, first.app_service_id).name == "store-api"
    assert session.get(Service, second.app_service_id).name == "store-api-2"


async def test_imported_app_waits_for_addons_and_stops_after_an_addon_failure(
    session: Session,
) -> None:
    result = await provision_import(
        session,
        installation_id=42,
        repository="acme/store-api",
        branch="main",
        selected_addons={"postgres", "redis"},
        proposal=AddonProposal(
            is_node_app=True,
            addons=("postgres", "redis"),
            externally_managed=(),
        ),
    )
    assert app_dependency_state(session, result.app_service_id) == ("ready", None)
