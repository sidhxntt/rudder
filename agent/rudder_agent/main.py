"""Node agent.

D3(b): this is the real component, built in Phase 1 and running on localhost.
Phase 2 changes where it runs, not what it is. The control plane owns desired
state; this process owns actual state on one host and never makes placement
decisions, never reads the control plane database, and does no variable
resolution.

HTTP surface:
    GET    /healthz                      liveness
    POST   /containers                   create + start from a ContainerSpec
    GET    /containers/{id}              inspect actual state
    DELETE /containers/{id}              drain (D10) then stop + remove
    POST   /containers/{id}/health       run exactly ONE health probe

Errors are uniform `{code, message, details}` per the PRD API design rules.
"""

from __future__ import annotations

import logging
from typing import Any

import docker
import docker.errors
from aiohttp import web
from pydantic import ValidationError

from . import errors
from .config import AgentSettings
from .docker_ops import DockerOps
from .schemas import ContainerSpec, HealthProbeRequest

log = logging.getLogger("rudder_agent")

OPS_KEY = web.AppKey("ops", DockerOps)
SETTINGS_KEY = web.AppKey("settings", AgentSettings)


def _error_response(err: errors.AgentError) -> web.Response:
    return web.json_response(err.body().model_dump(), status=err.status)


@web.middleware
async def error_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    """Every failure leaves this process in the uniform error shape. A container
    that does not exist is a 404, never a traceback."""
    try:
        return await handler(request)
    except errors.AgentError as exc:
        return _error_response(exc)
    except web.HTTPException as exc:
        if exc.status < 400:
            raise
        return _error_response(
            errors.AgentError(exc.status, _http_code(exc.status), exc.reason or "HTTP error")
        )
    except docker.errors.DockerException as exc:
        # Backstop: anything the ops layer failed to classify.
        log.exception("unclassified docker failure")
        return _error_response(errors.docker_error(str(exc)))
    except Exception as exc:
        log.exception("unhandled agent failure")
        return _error_response(
            errors.AgentError(500, "internal_error", f"{type(exc).__name__}: {exc}")
        )


def _http_code(status: int) -> str:
    return {404: "not_found", 405: "method_not_allowed", 400: "invalid_request"}.get(
        status, "http_error"
    )


async def _read_model(request: web.Request, model: type[Any]) -> Any:
    try:
        raw = await request.json()
    except ValueError as exc:
        raise errors.invalid_request(
            "Request body is not valid JSON", {"reason": str(exc)}
        ) from exc
    if not isinstance(raw, dict):
        raise errors.invalid_request("Request body must be a JSON object")
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        raise errors.invalid_request(
            f"Request body does not match {model.__name__}",
            {"errors": exc.errors(include_url=False, include_context=False)},
        ) from exc


# --------------------------------------------------------------------- handlers


async def healthz(request: web.Request) -> web.Response:
    return web.json_response({"status": "ok"})


async def create_container(request: web.Request) -> web.Response:
    spec: ContainerSpec = await _read_model(request, ContainerSpec)
    state = await request.app[OPS_KEY].create_and_start(spec)
    return web.json_response(state.model_dump(mode="json"), status=201)


async def get_container(request: web.Request) -> web.Response:
    container_id = request.match_info["container_id"]
    state = await request.app[OPS_KEY].inspect(container_id)
    return web.json_response(state.model_dump(mode="json"))


async def delete_container(request: web.Request) -> web.Response:
    container_id = request.match_info["container_id"]
    settings = request.app[SETTINGS_KEY]
    raw = request.query.get("drain_seconds")
    if raw is None:
        drain_seconds = settings.drain_seconds
    else:
        try:
            drain_seconds = float(raw)
        except ValueError as exc:
            raise errors.invalid_request(
                "drain_seconds must be a number", {"drain_seconds": raw}
            ) from exc
        if drain_seconds < 0:
            raise errors.invalid_request(
                "drain_seconds must not be negative", {"drain_seconds": raw}
            )
    result = await request.app[OPS_KEY].drain_and_remove(container_id, drain_seconds)
    return web.json_response(result.model_dump(mode="json"))


async def probe_container(request: web.Request) -> web.Response:
    container_id = request.match_info["container_id"]
    req: HealthProbeRequest = await _read_model(request, HealthProbeRequest)
    result = await request.app[OPS_KEY].probe(container_id, req)
    return web.json_response(result.model_dump(mode="json"))


# ------------------------------------------------------------------ app factory


def create_app(ops: DockerOps, settings: AgentSettings | None = None) -> web.Application:
    """Build the agent app around an injected DockerOps. Tests pass a fake
    Docker client through the constructor; nothing is monkeypatched."""
    app = web.Application(middlewares=[error_middleware])
    app[OPS_KEY] = ops
    app[SETTINGS_KEY] = settings or AgentSettings()
    app.add_routes(
        [
            web.get("/healthz", healthz),
            web.post("/containers", create_container),
            web.get("/containers/{container_id}", get_container),
            web.delete("/containers/{container_id}", delete_container),
            web.post("/containers/{container_id}/health", probe_container),
        ]
    )
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = AgentSettings()
    client = docker.from_env()
    ops = DockerOps(client, stop_timeout_seconds=settings.stop_timeout_seconds)
    web.run_app(create_app(ops, settings), host=settings.bind, port=settings.port)


if __name__ == "__main__":
    main()
