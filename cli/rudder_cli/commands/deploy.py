"""rudder deploy / rudder logs."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import typer
from rudder_sdk.api.deployments import create_deployment, get_deployment, list_deployments
from rudder_sdk.api.services import list_service_domains
from rudder_sdk.models import (
    DeploymentRead,
    DeploymentStatus,
    DeployRequest,
    DomainRead,
    ServiceRead,
)

from ..buildlog import (
    TERMINAL,
    _parse_events,
    follow_deployment,
    stream_build_log,
    wait_for_build_log,
)
from ..client import CliError
from ..context import State, resolve_service
from ..render import emit_json, err, out


def service_url(state: State, service: ServiceRead) -> str | None:
    domains: list[DomainRead] = (
        state.api.call(list_service_domains.sync_detailed, UUID(str(service.id))) or []
    )
    if not domains:
        return None
    domain = domains[0]
    scheme = "https" if domain.tls_enabled else "http"
    return f"{scheme}://{domain.hostname}"


def deploy(
    ctx: typer.Context,
    service: Annotated[
        str | None, typer.Argument(help="Service name or id. Defaults to the selected service.")
    ] = None,
    follow: Annotated[
        bool, typer.Option("--follow", "-f", help="Stream the build log and wait for the result.")
    ] = False,
    commit: Annotated[
        str | None,
        typer.Option("--commit", help="Deploy a specific SHA instead of the branch tip."),
    ] = None,
) -> None:
    """Queue a deployment. Exits non-zero if --follow and the deploy does not go live."""
    state: State = ctx.obj
    target = resolve_service(state, service)
    deployment: DeploymentRead = state.api.call(
        create_deployment.sync_detailed,
        UUID(str(target.id)),
        body=DeployRequest(commit_sha=commit) if commit else None,
    )

    if not follow:
        if state.json_out:
            emit_json(deployment.to_dict())
            return
        out(f"Queued deployment {deployment.id} for {target.name}.")
        out(f"Follow it with: rudder logs {target.name} -f")
        return

    out(f"Deploying {target.name} (deployment {deployment.id})")
    final = follow_deployment(state.api, UUID(str(deployment.id)))

    if state.json_out:
        emit_json(final.to_dict())
    if final.status is DeploymentStatus.LIVE:
        url = service_url(state, target)
        out(f"{target.name} is live" + (f" at {url}" if url else ""))
        return
    reason = final.error_message or "no reason recorded"
    err(f"Deployment {final.status.value}: {reason}")
    raise typer.Exit(code=1)


def logs(
    ctx: typer.Context,
    service: Annotated[
        str | None, typer.Argument(help="Service name or id. Defaults to the selected service.")
    ] = None,
    follow: Annotated[bool, typer.Option("--follow", "-f", help="Keep streaming.")] = False,
    deployment_id: Annotated[
        str | None, typer.Option("--deployment", help="A specific deployment id.")
    ] = None,
    build: Annotated[
        bool,
        typer.Option("--build", help="Stream the build log instead of runtime logs."),
    ] = False,
) -> None:
    """Runtime logs by default; use --build for the historical build log."""
    state: State = ctx.obj

    if not build:
        if deployment_id is not None:
            raise CliError("--deployment is only valid with --build")
        if not follow:
            raise CliError("Runtime logs are live; pass --follow (or -f).")
        target = resolve_service(state, service)
        with state.api.stream("GET", f"/services/{target.id}/runtime-log") as response:
            for _event, data in _parse_events(response.iter_lines()):
                if data:
                    out(data)
        return

    if deployment_id is not None:
        deployment: DeploymentRead = state.api.call(
            get_deployment.sync_detailed, UUID(deployment_id)
        )
    else:
        target = resolve_service(state, service)
        deployments: list[DeploymentRead] = (
            state.api.call(list_deployments.sync_detailed, UUID(str(target.id))) or []
        )
        if not deployments:
            raise CliError(
                f"{target.name} has no deployments yet. Run `rudder deploy {target.name}`."
            )
        deployment = deployments[0]  # the API returns newest first

    ident = UUID(str(deployment.id))
    try:
        result = stream_build_log(state.api, ident)
    except CliError as exc:
        if exc.status != 404:
            raise
        if not follow or deployment.status in TERMINAL:
            raise CliError(
                f"No build log for deployment {deployment.id} "
                f"(status {deployment.status.value}). The build never started."
            ) from exc
        out(f"Waiting for the build to start (deployment is {deployment.status.value})...")
        wait_for_build_log(state.api, ident)
        result = stream_build_log(state.api, ident)

    if result == "failed":
        err("build failed")
        raise typer.Exit(code=1)
