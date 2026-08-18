"""Authorization boundaries for explicit advisor proposal acceptance."""


from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from rudder_cp import config
from rudder_cp.db import get_session
from rudder_cp.models import Environment, Project, Service, User
from rudder_cp.routers import advisor
from rudder_cp.routers.auth import get_current_user


def test_variable_accept_rejects_a_service_outside_the_requested_environment(
    monkeypatch,
) -> None:
    """A proposal URL cannot be used to write a variable into another environment."""
    monkeypatch.setenv("RUDDER_SECRET_KEYS", Fernet.generate_key().decode())
    config.get_settings.cache_clear()
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            owner = User(email="owner@example.test", password_hash="unused")
            session.add(owner)
            session.commit()
            project = Project(name="project", owner_id=owner.id)
            session.add(project)
            session.commit()
            requested = Environment(project_id=project.id, name="requested")
            other = Environment(project_id=project.id, name="other")
            session.add(requested)
            session.add(other)
            session.commit()
            target = Service(environment_id=other.id, name="api")
            session.add(target)
            session.commit()

            app = FastAPI()
            app.include_router(advisor.router)
            app.dependency_overrides[get_session] = lambda: session
            app.dependency_overrides[get_current_user] = lambda: owner
            with TestClient(app) as client:
                response = client.post(
                    f"/environments/{requested.id}/advisor/accept",
                    json={
                        "item": {"kind": "variable", "payload": {"key": "DEBUG", "value": "0"}},
                        "service_id": str(target.id),
                    },
                )

        assert response.status_code == 404
    finally:
        SQLModel.metadata.drop_all(engine)
        config.get_settings.cache_clear()
