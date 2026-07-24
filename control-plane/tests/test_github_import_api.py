from collections.abc import Iterator
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from rudder_cp.config import get_settings
from rudder_cp.db import get_session
from rudder_cp.models import User
from rudder_cp.routers import imports as imports_router


class FakeGitHub:
    async def installations(self) -> list[object]:
        return [
            SimpleNamespace(
                id=42,
                account_login="acme",
                repository_selection="selected",
            )
        ]

    async def package_json(self, installation_id: int, repository: str, branch: str) -> dict:
        assert (installation_id, repository, branch) == (42, "acme/store-api", "main")
        return {"dependencies": {"express": "1", "pg": "1", "redis": "1"}}


def test_github_import_status_reports_setup_required_when_app_is_unconfigured(
    monkeypatch,
) -> None:
    monkeypatch.delenv("RUDDER_GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("RUDDER_GITHUB_APP_PRIVATE_KEY", raising=False)
    get_settings.cache_clear()
    try:
        app = FastAPI()
        app.state.settings = get_settings()
        app.include_router(imports_router.router)
        response = TestClient(app).get("/github/import/status")
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert response.json() == {
        "configured": False,
        "install_url": None,
        "message": "GitHub App credentials are not configured.",
    }


@pytest.fixture
def import_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("RUDDER_SECRET_KEYS", Fernet.generate_key().decode())
    get_settings.cache_clear()
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(email="owner@example.com", password_hash="x"))
        session.commit()

    app = FastAPI()
    app.state.settings = get_settings()
    app.state.github = FakeGitHub()
    app.include_router(imports_router.router)

    def override_get_session() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session
    with TestClient(app) as client:
        yield client
    engine.dispose()
    get_settings.cache_clear()


def test_confirm_import_creates_a_pollable_app_graph(import_client: TestClient) -> None:
    response = import_client.post(
        "/github/imports",
        json={
            "installation_id": 42,
            "repository": "acme/store-api",
            "branch": "main",
            "addons": ["postgres", "redis"],
        },
    )
    assert response.status_code == 201, response.text
    created = response.json()

    progress = import_client.get(f"/github/imports/{created['import_id']}")
    assert progress.status_code == 200, progress.text
    assert [step["label"] for step in progress.json()["steps"]] == [
        "Postgres",
        "Redis",
        "Application",
    ]
    assert all(step["status"] == "queued" for step in progress.json()["steps"])


def test_github_installations_lists_app_connections(import_client: TestClient) -> None:
    response = import_client.get("/github/import/installations")

    assert response.status_code == 200, response.text
    assert response.json() == [
        {
            "id": 42,
            "account_login": "acme",
            "repository_selection": "selected",
        }
    ]
