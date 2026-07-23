"""rudder project create|list|use."""

from __future__ import annotations

from uuid import UUID

import typer
from rudder_sdk.api.environments import list_environments
from rudder_sdk.api.projects import create_project, list_projects
from rudder_sdk.models import EnvironmentRead, ProjectCreate, ProjectRead

from ..context import (
    DEFAULT_ENVIRONMENT,
    State,
    resolve_project,
    select_environment,
    select_project,
)
from ..render import emit_json, out, table

app = typer.Typer(help="Projects.", no_args_is_help=True)


def _select_default_environment(state: State, project: ProjectRead) -> str | None:
    """A new project comes with `production`. Select it so `service create` works."""
    environments: list[EnvironmentRead] = (
        state.api.call(list_environments.sync_detailed, UUID(str(project.id))) or []
    )
    chosen = next(
        (e for e in environments if e.name == DEFAULT_ENVIRONMENT),
        environments[0] if len(environments) == 1 else None,
    )
    if chosen is None:
        return None
    select_environment(state, chosen)
    return chosen.name


@app.command("create")
def create(ctx: typer.Context, name: str) -> None:
    """Create a project (and its `production` environment) and select it."""
    state: State = ctx.obj
    project: ProjectRead = state.api.call(
        create_project.sync_detailed, body=ProjectCreate(name=name)
    )
    select_project(state, project)
    environment = _select_default_environment(state, project)
    if state.json_out:
        emit_json(project.to_dict())
        return
    out(f"Created project {project.name} ({project.id})")
    if environment:
        out(f"Selected project {project.name}, environment {environment}.")


@app.command("list")
def list_(ctx: typer.Context) -> None:
    """List projects."""
    state: State = ctx.obj
    projects: list[ProjectRead] = state.api.call(list_projects.sync_detailed) or []
    if state.json_out:
        emit_json([p.to_dict() for p in projects])
        return
    current = state.context.project.id if state.context.project else None
    table(
        ["", "NAME", "ID", "CREATED"],
        [
            [
                "*" if str(p.id) == current else "",
                p.name,
                str(p.id),
                p.created_at.isoformat(timespec="seconds"),
            ]
            for p in projects
        ],
    )


@app.command("use")
def use(ctx: typer.Context, name: str) -> None:
    """Select the project later commands act on."""
    state: State = ctx.obj
    state.project_opt = name
    project = resolve_project(state)
    select_project(state, project)
    environment = _select_default_environment(state, project)
    out(f"Selected project {project.name} ({project.id})")
    if environment:
        out(f"Selected environment {environment}.")
