"""Build-log access must follow deployment ownership."""

import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from rudder_cp.db import get_session
from rudder_cp.logs.store import BuildLogStore, get_build_log_store
from rudder_cp.models import Deployment, Environment, Project, Service, User
from rudder_cp.routers import logs
from rudder_cp.routers.auth import get_current_user
from rudder_cp.schemas.common import install_error_handlers


def test_build_log_hides_another_users_deployment(tmp_path) -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            owner = User(email="owner@example.test", password_hash="unused")
            caller = User(email="caller@example.test", password_hash="unused")
            session.add(owner)
            session.add(caller)
            session.commit()
            project = Project(name="private", owner_id=owner.id)
            session.add(project)
            session.commit()
            environment = Environment(project_id=project.id, name="production")
            session.add(environment)
            session.commit()
            service = Service(environment_id=environment.id, name="api")
            session.add(service)
            session.commit()
            deployment = Deployment(service_id=service.id)
            session.add(deployment)
            session.commit()

            store = BuildLogStore(tmp_path / "logs")
            asyncio.run(store.open_log(deployment.id))
            asyncio.run(store.close_log(deployment.id, "succeeded"))
            app = FastAPI()
            install_error_handlers(app)
            app.include_router(logs.router)
            app.dependency_overrides[get_session] = lambda: session
            app.dependency_overrides[get_build_log_store] = lambda: store
            app.dependency_overrides[get_current_user] = lambda: caller
            with TestClient(app) as client:
                response = client.get(f"/deployments/{deployment.id}/build-log")

        assert response.status_code == 404
    finally:
        SQLModel.metadata.drop_all(engine)
