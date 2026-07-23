"""rudder env create|list|use."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import typer
from rudder_sdk.api.environments import create_environment, list_environments
from rudder_sdk.models import EnvironmentCreate, EnvironmentRead

from ..context import State, resolve_environment, resolve_project, select_environment
from ..render import emit_json, out, table

app = typer.Typer(help="Environments within a project.", no_args_is_help=True)


@app.command("create")
def create(
    ctx: typer.Context,
    name: str,
    production: Annotated[
        bool, typer.Option("--production", help="Mark this environment as production.")
    ] = False,
) -> None:
    """Create an environment in the selected project and select it."""
    state: State = ctx.obj
    project = resolve_project(state)
    environment: EnvironmentRead = state.api.call(
        create_environment.sync_detailed,
        UUID(str(project.id)),
        body=EnvironmentCreate(name=name, is_production=production),
    )
    select_environment(state, environment)
    if state.json_out:
        emit_json(environment.to_dict())
        return
    out(f"Created environment {environment.name} ({environment.id}) in {project.name}")
    out(f"Selected environment {environment.name}.")


@app.command("list")
def list_(ctx: typer.Context) -> None:
    """List the selected project's environments."""
    state: State = ctx.obj
    project = resolve_project(state)
    environments: list[EnvironmentRead] = (
        state.api.call(list_environments.sync_detailed, UUID(str(project.id))) or []
    )
    if state.json_out:
        emit_json([e.to_dict() for e in environments])
        return
    current = state.context.environment.id if state.context.environment else None
    table(
        ["", "NAME", "ID", "PRODUCTION", "WG_SUBNET"],
        [
            [
                "*" if str(e.id) == current else "",
                e.name,
                str(e.id),
                "yes" if e.is_production else "no",
                str(e.wg_subnet or "-"),
            ]
            for e in environments
        ],
    )


@app.command("use")
def use(ctx: typer.Context, name: str) -> None:
    """Select the environment later commands act on."""
    state: State = ctx.obj
    state.env_opt = name
    environment = resolve_environment(state)
    select_environment(state, environment)
    out(f"Selected environment {environment.name} ({environment.id})")
