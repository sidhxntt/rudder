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

import asyncio
import logging
from typing import Any

import docker
import docker.errors
from aiohttp import web
from pydantic import ValidationError

from . import errors
from .config import AgentSettings
from .control_plane_client import ControlPlaneClient
from .docker_ops import DockerOps
from .schemas import ComposeProjectRequest, ComposeUpRequest, ContainerSpec, HealthProbeRequest

log = logging.getLogger("rudder_agent")

OPS_KEY = web.AppKey("ops", DockerOps)
SETTINGS_KEY = web.AppKey("settings", AgentSettings)
CLIENT_KEY = web.AppKey("client", ControlPlaneClient)
HEARTBEAT_TASK_KEY = web.AppKey("heartbeat_task", "Task[None]")


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


@web.middleware
async def control_plane_auth_middleware(
    request: web.Request, handler: Any
) -> web.StreamResponse:
    """Require the shared secret for control-plane commands, not liveness."""
    if request.path != "/healthz":
        settings = request.app[SETTINGS_KEY]
        if request.headers.get("X-Rudder-Agent-Secret") != settings.shared_secret:
            return _error_response(errors.AgentError(401, "unauthorized", "Invalid agent secret"))
    return await handler(request)


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


async def runtime_logs(request: web.Request) -> web.Response:
    container_id = request.match_info["container_id"]
    raw_limit = request.query.get("max_bytes", "65536")
    try:
        max_bytes = int(raw_limit)
    except ValueError as exc:
        raise errors.invalid_request("max_bytes must be an integer", {"max_bytes": raw_limit}) from exc
    if not 1 <= max_bytes <= 1_048_576:
        raise errors.invalid_request("max_bytes must be between 1 and 1048576", {"max_bytes": raw_limit})
    snapshot = await request.app[OPS_KEY].runtime_logs(container_id, max_bytes=max_bytes)
    return web.json_response(snapshot.model_dump())


async def runtime_metrics(request: web.Request) -> web.Response:
    metrics = await request.app[OPS_KEY].runtime_metrics(request.match_info["container_id"])
    return web.json_response(metrics.model_dump())


async def compose_up(request: web.Request) -> web.Response:
    payload: ComposeUpRequest = await _read_model(request, ComposeUpRequest)
    result = await request.app[OPS_KEY].compose_up(payload.project_name, payload.manifest)
    return web.json_response(result.model_dump(mode="json"))


async def compose_down(request: web.Request) -> web.Response:
    payload: ComposeProjectRequest = await _read_model(request, ComposeProjectRequest)
    result = await request.app[OPS_KEY].compose_down(payload.project_name)
    return web.json_response(result.model_dump(mode="json"))


async def compose_ps(request: web.Request) -> web.Response:
    project_name = request.match_info["project_name"]
    payload = ComposeProjectRequest(project_name=project_name)
    states = await request.app[OPS_KEY].compose_ps(payload.project_name)
    return web.json_response([state.model_dump(mode="json") for state in states])


# ------------------------------------------------------------------ app factory


async def heartbeat_background_task(app: web.Application) -> None:
    """Background task that sends heartbeats to the control plane."""
    client = app[CLIENT_KEY]
    while True:
        try:
            await client.heartbeat()
        except Exception:
            log.exception("unhandled exception in heartbeat")
        await asyncio.sleep(5)


async def on_startup(app: web.Application) -> None:
    """Register with the control plane and start the heartbeat task."""
    client = app[CLIENT_KEY]
    try:
        await client.register()
    except Exception:
        # If we can't register, there's no point in starting the agent.
        log.exception("failed to register with control plane, shutting down")
        # This is a bit of a hack to shut down the app from a startup signal.
        # It's not clean, but it's effective.
        asyncio.create_task(app.shutdown())
        return

    app[HEARTBEAT_TASK_KEY] = asyncio.create_task(heartbeat_background_task(app))


async def on_cleanup(app: web.Application) -> None:
    """Cancel the heartbeat task and close the client session."""
    if HEARTBEAT_TASK_KEY in app:
        app[HEARTBEAT_TASK_KEY].cancel()
        try:
            await app[HEARTBEAT_TASK_KEY]
        except asyncio.CancelledError:
            pass
    await app[CLIENT_KEY].close()


def create_app(ops: DockerOps, settings: AgentSettings | None = None) -> web.Application:
    """Build the agent app around an injected DockerOps. Tests pass a fake
    Docker client through the constructor; nothing is monkeypatched."""
    app = web.Application(middlewares=[error_middleware, control_plane_auth_middleware])
    app[OPS_KEY] = ops
    app[SETTINGS_KEY] = settings or AgentSettings()
    app[CLIENT_KEY] = ControlPlaneClient(app[SETTINGS_KEY], app[OPS_KEY])

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    app.add_routes(
        [
            web.get("/healthz", healthz),
            web.post("/containers", create_container),
            web.get("/containers/{container_id}", get_container),
            web.delete("/containers/{container_id}", delete_container),
            web.post("/containers/{container_id}/health", probe_container),
            web.get("/containers/{container_id}/runtime-logs", runtime_logs),
            web.get("/containers/{container_id}/metrics", runtime_metrics),
            web.post("/compose/up", compose_up),
            web.post("/compose/down", compose_down),
            web.get("/compose/{project_name}/ps", compose_ps),
        ]
    )
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    settings = AgentSettings()
    client = docker.from_env()
    ops = DockerOps(
        client,
        stop_timeout_seconds=settings.stop_timeout_seconds,
        compose_state_dir=settings.compose_state_dir,
    )
    web.run_app(create_app(ops, settings), host=settings.bind, port=settings.port)


if __name__ == "__main__":
    main()
