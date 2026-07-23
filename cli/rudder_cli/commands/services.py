"""rudder service create|list|delete|use."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import typer
from rudder_sdk.api.services import create_service, delete_service, list_services
from rudder_sdk.models import ServiceCreate, ServiceRead
from rudder_sdk.types import UNSET

from ..client import CliError
from ..context import State, resolve_environment, resolve_service, select_service
from ..render import emit_json, out, table

app = typer.Typer(help="Services within an environment.", no_args_is_help=True)


@app.command("create")
def create(
    ctx: typer.Context,
    name: str,
    repo: Annotated[
        str | None, typer.Option("--repo", help="GitHub owner/repo to build from.")
    ] = None,
    port: Annotated[
        int, typer.Option("--port", help="Port the app listens on. Traefik routes here.")
    ] = 8080,
    branch: Annotated[str, typer.Option("--branch", help="Branch to deploy.")] = "main",
    start_command: Annotated[
        str | None, typer.Option("--start-command", help="Overrides the image CMD.")
    ] = None,
    dockerfile: Annotated[
        str | None,
        typer.Option("--dockerfile", help="Path to a Dockerfile. Omit to generate one."),
    ] = None,
    health_path: Annotated[
        str, typer.Option("--health-path", help="Path polled until it returns 200.")
    ] = "/",
    health_port: Annotated[
        int | None, typer.Option("--health-port", help="Defaults to --port.")
    ] = None,
    cpu: Annotated[float, typer.Option("--cpu", help="CPU cores.")] = 1.0,
    memory: Annotated[int, typer.Option("--memory", help="Memory cap, MiB.")] = 512,
) -> None:
    """Create a service in the selected environment and select it."""
    state: State = ctx.obj
    environment = resolve_environment(state)
    service: ServiceRead = state.api.call(
        create_service.sync_detailed,
        UUID(str(environment.id)),
        body=ServiceCreate(
            name=name,
            source_repo=repo if repo is not None else UNSET,
            source_branch=branch,
            dockerfile_path=dockerfile if dockerfile is not None else UNSET,
            start_command=start_command if start_command is not None else UNSET,
            container_port=port,
            health_check_path=health_path,
            health_check_port=health_port if health_port is not None else UNSET,
            cpu_limit=cpu,
            memory_limit_mb=memory,
        ),
    )
    select_service(state, service)
    if state.json_out:
        emit_json(service.to_dict())
        return
    out(f"Created service {service.name} ({service.id}) in {environment.name}")
    out(f"  repo   {service.source_repo or '-'} @ {service.source_branch}")
    out(f"  port   {service.container_port}")
    out(f"Selected service {service.name}.")


@app.command("list")
def list_(ctx: typer.Context) -> None:
    """List services in the selected environment."""
    state: State = ctx.obj
    environment = resolve_environment(state)
    services: list[ServiceRead] = (
        state.api.call(list_services.sync_detailed, UUID(str(environment.id))) or []
    )
    if state.json_out:
        emit_json([s.to_dict() for s in services])
        return
    current = state.context.service.id if state.context.service else None
    table(
        ["", "NAME", "KIND", "REPO", "BRANCH", "PORT", "ID"],
        [
            [
                "*" if str(s.id) == current else "",
                s.name,
                s.kind.value,
                str(s.source_repo or "-"),
                s.source_branch,
                str(s.container_port),
                str(s.id),
            ]
            for s in services
        ],
    )


@app.command("delete")
def delete(
    ctx: typer.Context,
    name: str,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation.")] = False,
) -> None:
    """Delete a service."""
    state: State = ctx.obj
    service = resolve_service(state, name)
    if not yes and not typer.confirm(f"Delete service {service.name} ({service.id})?"):
        raise CliError("Aborted.")
    state.api.call(delete_service.sync_detailed, UUID(str(service.id)))
    if state.context.service and state.context.service.id == str(service.id):
        state.context.service = None
        state.context.save()
    out(f"Deleted service {service.name}.")


@app.command("use")
def use(ctx: typer.Context, name: str) -> None:
    """Select the service that `var` and `deploy` act on by default."""
    state: State = ctx.obj
    service = resolve_service(state, name)
    select_service(state, service)
    out(f"Selected service {service.name} ({service.id})")
