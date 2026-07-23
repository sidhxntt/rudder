# cli

`rudder` — a thin wrapper over `sdk-python`. Phase 1 step 9.

Every command is one or more calls into the generated SDK. There is no logic
here the API does not already have: if the CLI can do it, so can the UI and any
other client. If something needed a CLI-side workaround, that would be an API
bug, not a CLI feature.

## Install

```bash
pip install -e sdk-python -e cli
rudder --help
```

Typer, not Click: every command is "some options, one API call, print the
result", and Typer derives the parser from the type hints this repo writes
anyway. Click would mean restating each parameter as a decorator for no gain.
(Typer 0.27 vendors Click, so nothing here imports `click`.)

## Commands

```
rudder login [--email E] [--password P] [--url URL]   password is prompted for if omitted
rudder logout
rudder whoami

rudder project create NAME
rudder project list
rudder project use NAME

rudder env create NAME [--production]
rudder env list
rudder env use NAME

rudder service create NAME --repo OWNER/REPO --port N
       [--branch main] [--start-command CMD] [--dockerfile PATH]
       [--health-path /] [--health-port N] [--cpu 1.0] [--memory 512]
rudder service list
rudder service delete NAME [--yes]
rudder service use NAME

rudder var set KEY=VALUE [KEY=VALUE ...] [--service NAME]
rudder var list [--service NAME]
rudder var unset KEY [--service NAME]

rudder deploy [SERVICE] [--follow] [--commit SHA]
rudder logs [SERVICE] [-f] [--deployment ID]
rudder status          # alias: rudder ps
```

Global options come **before** the subcommand: `rudder --json status`,
`rudder --project shop service list`.

| | |
|---|---|
| `--url` | control plane URL (`RUDDER_URL`); otherwise the one saved at login |
| `--project` / `-p` | project name or id, overriding the selected one |
| `--env` / `-e` | environment name or id, overriding the selected one |
| `--json` | `json.dumps` of the response, for scripts |

## How a name becomes an id

The API addresses everything by UUID; `Service.name` is unique only within an
environment. Resolution order, in `rudder_cli/context.py`:

1. **An explicit flag** — `--project`, `--env`, `--service`. A UUID is accepted
   anywhere a name is and short-circuits the lookup.
2. **The saved context** — `~/.config/rudder/context.json`, written by
   `project use` / `env use` / `service use` and as a side effect of the
   matching `create`. This is what makes the PRD's acceptance script work:
   `rudder var set DATABASE_URL=...` names no service because
   `rudder service create api` already selected one.
3. **One fallback, for the environment only** — a project with exactly one
   environment uses it; otherwise the one named `production`, which every
   project is created with.

There is no fallback for project or service, no prefix matching, and no
arbitrary pick. `Project.name` has no uniqueness constraint, so two projects can
share a name; that is an error listing both ids, never a coin flip:

```
$ rudder --project acceptance service list
error: 2 projects are named 'acceptance'. Pass the id instead:
  d92caa31-0301-4ca5-9280-540e9efb4a11  acceptance
  b6a23b8e-d3e8-4739-8d9d-a80f71f9e522  acceptance
```

## Where the token lives

`rudder login` POSTs to `/auth/token` and writes the bearer token to
`$RUDDER_CONFIG_DIR`, else `$XDG_CONFIG_HOME/rudder`, else
`~/.config/rudder`:

```
~/.config/rudder/credentials.json   0600   {"base_url", "access_token", "expires_at"}
~/.config/rudder/context.json       0600   selected project / environment / service
```

Directory 0700, files 0600, written via `os.open(..., 0o600)` and an atomic
rename — never `open()` then `chmod`. The token is never printed, never put in
an environment variable, and `--password` exists only for automation: without it
the password is read from a hidden prompt so it stays out of shell history.

## Variables are write-only

`PUT /services/{id}/variables/{key}` takes a value and returns
`{id, service_id, key, is_reference, created_at}`. No endpoint in this API ever
returns a variable's value. `rudder var list` therefore shows keys and whether
each is a `${{service.VAR}}` reference, and says so:

```
$ rudder var list
KEY           KIND
------------  ---------
DATABASE_URL  reference
GREETING      literal

Values are write-only and are never returned by the API.
```

## Following a build

`--follow` streams `GET /deployments/{id}/build-log` (SSE) and then **keeps
going**. The stream's `event: end` is written by the *builder*, so
`data: succeeded` means the image was built and pushed — the container start,
the health check and the Traefik write all happen after the stream closes. So
`deploy --follow` polls the deployment to a terminal status and exits 0 only for
`live`:

| outcome | exit |
|---|---|
| deployment reaches `live` | 0 |
| build failed, or deployment `failed` / `superseded` | 1 |
| control plane unreachable, no such service, bad usage | 1 (2 for usage) |

A queued deploy has no log file yet and the endpoint 404s rather than hanging;
the CLI waits for it to appear (bounded, 120s) and says what it is waiting for.
`rudder logs` on a deployment that never produced a log says so and exits 1
instead of hanging.

## Errors

API errors are the uniform `{code, message, details}`. The CLI prints
`error: <message>` on stderr and exits non-zero. No tracebacks:

```
$ rudder --url http://localhost:9 project list
error: Cannot reach the Rudder control plane at http://localhost:9 — is it running?

$ rudder deploy nosource
error: This service has no source_repo, so there is nothing to build.
```

## Style

`ruff check` and `ruff format` clean at line-length 100, `target-version =
py312`, type hints throughout, no bare `except`.
