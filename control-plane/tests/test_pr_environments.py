"""Phase 5 pull-request environment lifecycle tests."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from rudder_cp.config import Settings
from rudder_cp.models import Deployment, Environment, GitHubImport, Project, Service, User
from rudder_cp.services.environments import handle_pull_request


class FakeGitHub:
    def __init__(self) -> None:
        self.comments: list[tuple[object, ...]] = []

    async def comment_on_pull_request(self, *_args: object) -> None:
        self.comments.append(_args)


def _payload(action: str, *, number: int = 42, branch: str = "feature/login") -> dict[str, object]:
    return {
        "action": action,
        "number": number,
        "repository": {"full_name": "acme/shop"},
        "pull_request": {"head": {"ref": branch, "sha": "a" * 40}},
    }


@pytest.fixture
def session() -> Session:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    result = Session(engine)
    user = User(email=f"{uuid.uuid4()}@example.test", password_hash="x")
    result.add(user)
    result.commit()
    project = Project(name="shop", owner_id=user.id)
    result.add(project)
    result.commit()
    environment = Environment(project_id=project.id, name="production", is_production=True)
    result.add(environment)
    result.commit()
    result.add(
        Service(
            environment_id=environment.id,
            name="api",
            source_repo="acme/shop",
            source_branch="main",
            canvas_x=80,
            canvas_y=120,
        )
    )
    result.commit()
    app = result.exec(select(Service).where(Service.environment_id == environment.id)).one()
    result.add(
        GitHubImport(
            installation_id=1,
            repository="acme/shop",
            branch="main",
            compose_source="compose.yml",
            compose_manifest="services: {}",
            compose_project_name=f"shop-{uuid.uuid4().hex[:8]}",
            project_id=project.id,
            app_service_id=app.id,
        )
    )
    result.commit()
    yield result
    result.close()
    engine.dispose()


@pytest.mark.asyncio
async def test_pr_open_replay_and_close_are_idempotent(session: Session, tmp_path) -> None:
    settings = Settings(traefik_dynamic_dir=str(tmp_path))
    github = FakeGitHub()
    created = await handle_pull_request(
        session,
        payload=_payload("opened"),
        agent=object(),  # no instances exist, so close never calls it
        settings=settings,
        github=github,  # type: ignore[arg-type]
    )
    assert created["detail"] == "created"
    preview = session.exec(select(Environment).where(Environment.github_pr_number == 42)).one()
    assert preview.name == f"pr-42-{preview.project_id.hex[:8]}"
    cloned_service = session.exec(select(Service).where(Service.environment_id == preview.id)).one()
    assert cloned_service.source_branch == "feature/login"
    assert cloned_service.canvas_x == 80
    assert (
        session.exec(select(Deployment).where(Deployment.service_id == cloned_service.id))
        .one()
        .commit_sha
        == "a" * 40
    )
    assert github.comments[0][3] == (
        f"Rudder PR environment: http://api.pr-42-{preview.project_id.hex[:8]}.localhost"
    )

    replayed = await handle_pull_request(
        session,
        payload=_payload("opened"),
        agent=object(),
        settings=settings,
        github=github,  # type: ignore[arg-type]
    )
    assert replayed["detail"] == "updated"
    assert session.exec(select(Environment).where(Environment.github_pr_number == 42)).all() == [
        preview
    ]
    assert (
        session.exec(select(Deployment).where(Deployment.service_id == cloned_service.id))
        .all()
        .__len__()
        == 1
    )

    closed = await handle_pull_request(
        session,
        payload=_payload("closed"),
        agent=object(),
        settings=settings,
        github=github,  # type: ignore[arg-type]
    )
    assert closed["detail"] == "destroyed"
    assert session.exec(select(Environment).where(Environment.github_pr_number == 42)).all() == []
    assert (
        await handle_pull_request(
            session,
            payload=_payload("closed"),
            agent=object(),
            settings=settings,
            github=github,  # type: ignore[arg-type]
        )
    )["detail"] == "already absent"


def test_project_can_have_only_one_environment_for_a_pr(session: Session) -> None:
    project_id = session.exec(select(Project.id)).one()
    session.add(Environment(project_id=project_id, name="pr-99", github_pr_number=99))
    session.commit()
    session.add(Environment(project_id=project_id, name="pr-99-retry", github_pr_number=99))
    with pytest.raises(IntegrityError):
        session.commit()
