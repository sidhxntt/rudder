"""rudder env create|clone|destroy|list|use."""

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
        ["", "NAME", "ID", "PRODUCTION", "PR"],
        [
            [
                "*" if str(e.id) == current else "",
                e.name,
                str(e.id),
                "yes" if e.is_production else "no",
                str(getattr(e, "github_pr_number", None) or "-"),
            ]
            for e in environments
        ],
    )


@app.command("clone")
def clone(ctx: typer.Context, name: str) -> None:
    """Clone the selected environment's declarative graph and select it."""
    state: State = ctx.obj
    source = resolve_environment(state)
    result = state.api.request_json(
        "POST", f"/environments/{source.id}/clone", json={"name": name}
    )
    environment = EnvironmentRead.from_dict(result)
    select_environment(state, environment)
    if state.json_out:
        emit_json(environment.to_dict())
        return
    out(f"Cloned {source.name} to {environment.name} ({environment.id}).")
    out(f"Selected environment {environment.name}.")


@app.command("destroy")
def destroy(
    ctx: typer.Context,
    yes: Annotated[bool, typer.Option("--yes", help="Confirm deletion.")] = False,
) -> None:
    """Destroy the selected non-production environment and all its data."""
    state: State = ctx.obj
    environment = resolve_environment(state)
    if environment.is_production:
        raise typer.BadParameter("refusing to destroy the production environment")
    if not yes:
        raise typer.BadParameter("pass --yes to destroy an environment")
    state.api.request_json("DELETE", f"/environments/{environment.id}")
    state.context.environment = None
    state.context.service = None
    state.context.save()
    out(f"Destroyed environment {environment.name}.")


@app.command("use")
def use(ctx: typer.Context, name: str) -> None:
    """Select the environment later commands act on."""
    state: State = ctx.obj
    state.env_opt = name
    environment = resolve_environment(state)
    select_environment(state, environment)
    out(f"Selected environment {environment.name} ({environment.id})")
