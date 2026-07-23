"""Turning a name into a UUID.

The API addresses everything by UUID. The CLI names things: ``rudder deploy api``.
Service names are unique only within an environment, so a name is meaningless
without one, and the CLI resolves in a fixed order:

1. an explicit flag — ``--project``, ``--env``, ``--service`` (a UUID is accepted
   anywhere a name is, and short-circuits the lookup)
2. the saved context — ``rudder project use`` / ``env use`` / ``service use``,
   also set as a side effect of the matching ``create``
3. one documented fallback for the environment only: a project with exactly one
   environment uses it, otherwise the one named ``production`` (which every
   project is created with)

There is no fallback for project or service. Nothing is ever guessed from a
partial match, and a name that matches more than one row is an error naming the
candidates — never an arbitrary pick.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from rudder_sdk.api.environments import get_environment, list_environments
from rudder_sdk.api.projects import get_project, list_projects
from rudder_sdk.api.services import get_service, list_services
from rudder_sdk.models import EnvironmentRead, ProjectRead, ServiceRead

from .client import Api, CliError
from .config import Context, Selection

DEFAULT_ENVIRONMENT = "production"


@dataclass(slots=True)
class State:
    """Everything a command needs. Built once in the root callback."""

    api: Api
    context: Context
    project_opt: str | None = None
    env_opt: str | None = None
    json_out: bool = False


def _as_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None


def _pick(name: str, matches: list[ProjectRead], kind: str) -> ProjectRead:
    if len(matches) == 1:
        return matches[0]
    ids = "\n  ".join(f"{m.id}  {m.name}" for m in matches)
    raise CliError(f"{len(matches)} {kind}s are named {name!r}. Pass the id instead:\n  {ids}")


def resolve_project(state: State) -> ProjectRead:
    if state.project_opt:
        wanted = state.project_opt
        as_id = _as_uuid(wanted)
        if as_id is not None:
            return state.api.call(get_project.sync_detailed, as_id)
        projects: list[ProjectRead] = state.api.call(list_projects.sync_detailed) or []
        matches = [p for p in projects if p.name == wanted]
        if not matches:
            known = ", ".join(sorted(p.name for p in projects)) or "none"
            raise CliError(f"No project named {wanted!r}. Known projects: {known}")
        return _pick(wanted, matches, "project")

    if state.context.project:
        return state.api.call(get_project.sync_detailed, UUID(state.context.project.id))

    raise CliError("No project selected. Run `rudder project use <name>` or pass --project <name>.")


def resolve_environment(state: State) -> EnvironmentRead:
    project = resolve_project(state)
    environments: list[EnvironmentRead] = (
        state.api.call(list_environments.sync_detailed, UUID(str(project.id))) or []
    )

    if state.env_opt:
        wanted = state.env_opt
        as_id = _as_uuid(wanted)
        if as_id is not None:
            environment = state.api.call(get_environment.sync_detailed, as_id)
            if str(environment.project_id) != str(project.id):
                raise CliError(
                    f"Environment {wanted} belongs to a different project than {project.name!r}."
                )
            return environment
        # unique(project_id, name) in the schema — at most one match, ever.
        for environment in environments:
            if environment.name == wanted:
                return environment
        known = ", ".join(sorted(e.name for e in environments)) or "none"
        raise CliError(
            f"No environment named {wanted!r} in project {project.name!r}. Known: {known}"
        )

    saved = state.context.environment
    if saved and not state.project_opt:
        for environment in environments:
            if str(environment.id) == saved.id:
                return environment

    if len(environments) == 1:
        return environments[0]
    for environment in environments:
        if environment.name == DEFAULT_ENVIRONMENT:
            return environment
    known = ", ".join(sorted(e.name for e in environments)) or "none"
    raise CliError(
        f"Project {project.name!r} has no {DEFAULT_ENVIRONMENT!r} environment and more "
        f"than one to choose from. Pass --env <name>. Known: {known}"
    )


def resolve_service(state: State, name: str | None) -> ServiceRead:
    environment = resolve_environment(state)

    if name is None:
        saved = state.context.service
        if saved is None:
            raise CliError(
                "No service given and none selected. Name one, or run `rudder service use <name>`."
            )
        name = saved.id

    as_id = _as_uuid(name)
    if as_id is not None:
        service = state.api.call(get_service.sync_detailed, as_id)
        if str(service.environment_id) != str(environment.id):
            raise CliError(
                f"Service {name} is not in environment {environment.name!r}. "
                "Pass --project/--env, or select it with `rudder service use`."
            )
        return service

    services: list[ServiceRead] = (
        state.api.call(list_services.sync_detailed, UUID(str(environment.id))) or []
    )
    # unique(environment_id, name) in the schema — at most one match, ever.
    for service in services:
        if service.name == name:
            return service
    known = ", ".join(sorted(s.name for s in services)) or "none"
    raise CliError(f"No service named {name!r} in {environment.name}. Known services: {known}")


def select_project(state: State, project: ProjectRead) -> None:
    state.context.project = Selection(id=str(project.id), name=project.name)
    state.context.environment = None
    state.context.service = None
    state.context.save()


def select_environment(state: State, environment: EnvironmentRead) -> None:
    state.context.environment = Selection(id=str(environment.id), name=environment.name)
    state.context.service = None
    state.context.save()


def select_service(state: State, service: ServiceRead) -> None:
    state.context.service = Selection(id=str(service.id), name=service.name)
    state.context.save()
