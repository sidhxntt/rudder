"""Confirmed GitHub imports create a private add-on graph before the app."""

from collections.abc import Iterator

import pytest
from cryptography.fernet import Fernet
from sqlmodel import Session, SQLModel, create_engine, select

from rudder_cp.config import get_settings
from rudder_cp.models import (
    Deployment,
    DeploymentStatus,
    Domain,
    GitHubImport,
    Service,
    User,
    Variable,
    Volume,
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
    assert [deployment.service_id for deployment in deployments] == [
        service.id for service in services
    ]

    record = session.get(GitHubImport, result.import_id)
    assert record is not None
    assert [step["label"] for step in import_progress(session, record)] == [
        "Postgres",
        "Redis",
        "Application",
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
    deployments = list(session.exec(select(Deployment).order_by(Deployment.created_at)).all())
    postgres, redis, _app = deployments

    postgres.status = DeploymentStatus.FAILED
    session.add(postgres)
    session.commit()
    assert app_dependency_state(session, result.app_service_id) == (
        "failed",
        "Postgres did not become live; application deployment was not started.",
    )

    postgres.status = DeploymentStatus.LIVE
    session.add(postgres)
    session.commit()
    assert app_dependency_state(session, result.app_service_id) == ("waiting", None)

    redis.status = DeploymentStatus.LIVE
    session.add(redis)
    session.commit()
    assert app_dependency_state(session, result.app_service_id) == ("ready", None)
