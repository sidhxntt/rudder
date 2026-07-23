"""login / logout / whoami."""

from __future__ import annotations

import time
from typing import Annotated

import typer
from rudder_sdk.api.auth import create_token_auth_token_post, read_me_auth_me_get
from rudder_sdk.models import LoginRequest, TokenResponse, UserRead

from ..client import CliError, connect
from ..config import DEFAULT_BASE_URL, Credentials
from ..context import State
from ..render import out


def login(
    ctx: typer.Context,
    email: Annotated[str | None, typer.Option("--email", help="Admin email.")] = None,
    password: Annotated[
        str | None,
        typer.Option(
            "--password",
            help="Prompted for if omitted. Prefer the prompt: an argument lands in shell history.",
        ),
    ] = None,
    url: Annotated[
        str | None, typer.Option("--url", help=f"Control plane URL. Default {DEFAULT_BASE_URL}.")
    ] = None,
) -> None:
    """Exchange email + password for an access token and store it 0600."""
    state: State = ctx.obj
    base_url = url or state.api.base_url
    if email is None:
        email = typer.prompt("Email")
    if password is None:
        password = typer.prompt("Password", hide_input=True)

    api = connect(base_url, token="")
    token: TokenResponse = api.call(
        create_token_auth_token_post.sync_detailed,
        body=LoginRequest(email=email, password=password),
    )

    credentials = Credentials(
        base_url=base_url,
        access_token=token.access_token,
        expires_at=time.time() + token.expires_in,
    )
    path = credentials.save()
    out(f"Logged in to {base_url} as {email}.")
    out(f"Token stored in {path} (mode 0600), valid for {token.expires_in}s.")


def logout() -> None:
    """Discard the stored token."""
    Credentials.clear()
    out("Logged out. Stored token deleted.")


def whoami(ctx: typer.Context) -> None:
    """Who the stored token belongs to."""
    state: State = ctx.obj
    user: UserRead | None = state.api.call(read_me_auth_me_get.sync_detailed)
    if user is None:
        raise CliError("Not authenticated. Run `rudder login`.")
    out(f"{user.email}  ({user.id})")
    out(f"control plane: {state.api.base_url}")
