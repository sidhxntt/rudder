"""``rudder`` — the CLI entry point.

Typer over Click: every command here is "some options, one API call, print it",
and Typer derives the whole parser from the type hints this codebase already
writes. Click would mean repeating each parameter as a decorator. Nothing here
needs Click's lower-level control.

The root callback builds one :class:`State` — client plus saved context — and
hangs it off ``ctx.obj``. Commands never construct a client themselves.

Exit codes: 0 success, 1 anything the user must fix (API error, no such service,
a build that failed), 2 Typer's own usage errors, 130 on Ctrl-C.
"""

from __future__ import annotations

import sys
from typing import Annotated

import typer

from .client import CliError, connect
from .commands import auth, deploy, environments, projects, services, status, variables
from .config import Context, Credentials
from .context import State
from .render import err

app = typer.Typer(
    name="rudder",
    help="Operate a Rudder control plane from the terminal.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)


@app.callback()
def root(
    ctx: typer.Context,
    url: Annotated[
        str | None,
        typer.Option("--url", envvar="RUDDER_URL", help="Control plane URL."),
    ] = None,
    project: Annotated[
        str | None,
        typer.Option("--project", "-p", help="Project name or id. Overrides the selected one."),
    ] = None,
    environment: Annotated[
        str | None,
        typer.Option("--env", "-e", help="Environment name or id. Overrides the selected one."),
    ] = None,
    json_out: Annotated[
        bool, typer.Option("--json", help="Machine-readable output where it applies.")
    ] = False,
) -> None:
    credentials = Credentials.load()
    base_url = url or credentials.base_url
    ctx.obj = State(
        api=connect(base_url, token=credentials.access_token or ""),
        context=Context.load(),
        project_opt=project,
        env_opt=environment,
        json_out=json_out,
    )


app.command("login")(auth.login)
app.command("logout")(auth.logout)
app.command("whoami")(auth.whoami)
app.add_typer(projects.app, name="project")
app.add_typer(environments.app, name="env")
app.add_typer(services.app, name="service")
app.add_typer(variables.app, name="var")
app.command("deploy")(deploy.deploy)
app.command("logs")(deploy.logs)
app.command("status")(status.status)
app.command("ps", help="Alias for `rudder status`.")(status.status)


def main() -> int:
    """Console-script entry point. Every deliberate failure is one line on stderr.

    Typer runs in its own standalone mode, so it keeps ownership of ``--help``,
    usage errors and ``typer.Exit`` — all of which reach here as ``SystemExit``.
    Only ``CliError`` escapes it, and that is the whole point: the user sees the
    API's message, never a traceback. (Typer vendors Click as of 0.27, so this
    deliberately imports neither.)
    """
    try:
        app()
    except CliError as exc:
        err(f"error: {exc.message}")
        return 1
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else (0 if code is None else 1)
    except KeyboardInterrupt:
        err("interrupted")
        return 130
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
