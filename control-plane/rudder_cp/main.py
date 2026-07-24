"""App factory, router mount, lifespan.

Long work never runs in a request. POST /services/{id}/deploy writes
Deployment(status=queued) and returns 202; the worker started here picks it up.
"""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlmodel import Session

from rudder_cp.config import Settings, get_settings
from rudder_cp.db import get_engine
from rudder_cp.logs.store import get_build_log_store
from rudder_cp.routers import auth as auth_router
from rudder_cp.routers import (
    deployments,
    domains,
    environments,
    imports,
    logs,
    projects,
    services,
    variables,
    webhooks,
)
from rudder_cp.schemas.common import install_error_handlers
from rudder_cp.services.agent_client import AgentClient
from rudder_cp.services.auth import seed_admin_user
from rudder_cp.services.github_app import GitHubAppClient
from rudder_cp.services.variables import verify_secret_keys
from rudder_cp.services.worker import run_worker

log = logging.getLogger("rudder_cp")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings

    # Fail at boot, not at the first deploy: a bad key list is a configuration
    # error and it should be visible before anything is encrypted.
    verify_secret_keys()

    engine = get_engine()
    with Session(engine) as session:
        await seed_admin_user(session)

    stop = asyncio.Event()
    worker = asyncio.create_task(
        run_worker(
            engine=engine,
            settings=settings,
            store=get_build_log_store(),
            agent=app.state.agent,
            stop=stop,
        ),
        name="deploy-worker",
    )
    log.info("deploy worker started")
    try:
        yield
    finally:
        stop.set()
        worker.cancel()
        # Shutdown must not hang on a build in flight.
        await asyncio.gather(worker, return_exceptions=True)
        log.info("deploy worker stopped")


def create_app() -> FastAPI:
    # uvicorn configures only its own loggers, so without this every worker,
    # deploy, and reconciliation line is silently discarded.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
    )

    app = FastAPI(title="Rudder Control Plane", version="0.1.0", lifespan=lifespan)
    settings = get_settings()
    app.state.settings = settings
    app.state.agent = AgentClient(settings.agent_url)
    app.state.github = GitHubAppClient(settings)

    # Both are needed: install_error_handlers flattens FastAPI's `detail`
    # nesting (including Pydantic 422s) into the PRD's {code, message, details},
    # and the auth handler covers the ApiError raised by the auth router.
    install_error_handlers(app)
    app.add_exception_handler(auth_router.ApiError, auth_router.api_error_handler)

    # Every resource router is protected here, in one place, rather than by a
    # dependency repeated on each route — one missed decorator would otherwise
    # leave an endpoint open, and `POST /services/{id}/deploy` runs arbitrary
    # code from a git repo.
    protected = (projects, environments, services, domains, variables, deployments, logs, imports)
    for module in protected:
        app.include_router(module.router, dependencies=[Depends(auth_router.get_current_user)])

    # auth issues the token, so it cannot require one. The webhook authenticates
    # with an HMAC over the request body instead — a GitHub push has no user.
    app.include_router(auth_router.router)
    app.include_router(webhooks.router)

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "tls_mode": settings.tls_mode}

    return app


app = create_app()
