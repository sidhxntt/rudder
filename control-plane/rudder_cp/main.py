"""App factory, router mount, lifespan.

The deploy worker (Phase 1 step 5) starts here. Long work never runs inside a
request: POST /services/{id}/deploy writes Deployment(status=queued) and returns
202; the worker picks it up.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from rudder_cp.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Phase 1 step 3 seeds the single user here.
    # Phase 1 step 5 starts the background deploy worker here.
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Rudder Control Plane",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "tls_mode": settings.tls_mode}

    return app


app = create_app()
