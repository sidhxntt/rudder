"""rudder var set|list|unset.

Values are write-only. ``PUT /services/{id}/variables/{key}`` accepts a value
and returns ``{id, service_id, key, is_reference, created_at}`` — no endpoint in
this API ever returns a variable's value, so ``var list`` shows keys and whether
each is a ``${{service.VAR}}`` reference. It does not show values and it does not
pretend to.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

import typer
from rudder_sdk.api.variables import (
    delete_variable_services_service_id_variables_key_delete as delete_variable,
)
from rudder_sdk.api.variables import (
    list_variables_services_service_id_variables_get as list_variables,
)
from rudder_sdk.api.variables import (
    set_variable_services_service_id_variables_key_put as set_variable,
)
from rudder_sdk.models import VariableRead, VariableUpsert

from ..client import CliError
from ..context import State, resolve_service
from ..render import emit_json, out, table

app = typer.Typer(
    help="Service environment variables (values are write-only).", no_args_is_help=True
)

ServiceOpt = Annotated[
    str | None,
    typer.Option("--service", "-s", help="Service name or id. Defaults to the selected service."),
]


@app.command("set")
def set_(
    ctx: typer.Context,
    assignments: Annotated[
        list[str],
        typer.Argument(help="KEY=VALUE. Quote the value so the shell leaves ${{...}} alone."),
    ],
    service: ServiceOpt = None,
) -> None:
    """Set one or more variables. Idempotent — same body twice, same result."""
    state: State = ctx.obj
    target = resolve_service(state, service)
    results: list[VariableRead] = []
    for assignment in assignments:
        key, separator, value = assignment.partition("=")
        if not separator or not key:
            raise CliError(f"Expected KEY=VALUE, got {assignment!r}.")
        results.append(
            state.api.call(
                set_variable.sync_detailed,
                UUID(str(target.id)),
                key,
                body=VariableUpsert(value=value),
            )
        )
    if state.json_out:
        emit_json([v.to_dict() for v in results])
        return
    for variable in results:
        kind = "reference" if variable.is_reference else "literal"
        out(f"Set {variable.key} on {target.name} ({kind}).")


@app.command("list")
def list_(ctx: typer.Context, service: ServiceOpt = None) -> None:
    """List variable keys. Values are never returned by the API."""
    state: State = ctx.obj
    target = resolve_service(state, service)
    variables: list[VariableRead] = (
        state.api.call(list_variables.sync_detailed, UUID(str(target.id))) or []
    )
    if state.json_out:
        emit_json([v.to_dict() for v in variables])
        return
    table(
        ["KEY", "KIND"],
        [[v.key, "reference" if v.is_reference else "literal"] for v in variables],
    )
    if variables:
        out()
        out("Values are write-only and are never returned by the API.")


@app.command("unset")
def unset(ctx: typer.Context, key: str, service: ServiceOpt = None) -> None:
    """Delete a variable."""
    state: State = ctx.obj
    target = resolve_service(state, service)
    state.api.call(delete_variable.sync_detailed, UUID(str(target.id)), key)
    out(f"Unset {key} on {target.name}.")
