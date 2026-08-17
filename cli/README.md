# Rudder CLI

`rudder` is the Node/TypeScript terminal client in [`node/`](node/). It talks
to the same authenticated Rudder control-plane API as the web console: it is
not a second backend and it does not perform a special terminal-to-browser
sync. Resources shown or changed by either client are the resources held by
that shared API.

In an interactive terminal, running `rudder` without a command opens the
guided launcher. It uses GitHub authentication, lets you select a project and
environment, and provides a small menu for common work such as deploys,
status, logs, services, variables, advisor, and signing out.

## Local setup

```bash
cd cli/node
npm install
npm link
rudder
```

`npm link` makes the local package available as the `rudder` command for this
machine. It is a local test/install step only: it does not publish a package
or push any Phase 9 changes.

## First interactive run

Start the Rudder control plane, then run `rudder` from a TTY. If there is no
saved session, Rudder asks the shared backend for a short-lived GitHub
authorization URL and opens it in your browser. Complete GitHub sign-in there;
the CLI waits for the same backend handoff to finish, saves the returned access
token locally, and opens the launcher. If it cannot open a browser, it prints
the URL so you can copy it yourself.

Choose **project/environment** from the launcher to persist the target for
subsequent commands. The menu then runs actions against that selected context.
You can still override it on a command with `--project`, `--env`, or
`--service`.

Set `RUDDER_URL` when the control plane is not at the local default:

```bash
RUDDER_URL=http://localhost:8000 rudder
```

## Saved session and logout

By default the CLI stores its Rudder URL, access token, and selected project,
environment, and service in `~/.config/rudder/config.json`. Set
`RUDDER_CONFIG` to use another config-file path. Treat that file as sensitive:
it contains the saved access token.

```bash
rudder context show
rudder logout
```

`rudder logout` removes the locally saved access token. It leaves the saved
Rudder URL and target context in place and does not revoke the GitHub or
backend session remotely.

## Automation and non-interactive use

Use a process-local token for scripts; it is not saved to the config file:

```bash
RUDDER_TOKEN=... rudder --no-interactive project list --json
```

`--no-interactive` never starts browser login or prompts. A command that needs
authentication must receive `RUDDER_TOKEN` (or use an already saved CLI
session when appropriate); otherwise it exits with a sign-in error. Commands
running without a TTY also never open the launcher or prompt for GitHub login.
Bare `rudder` in a non-TTY prints usage; invoke an explicit command with
`RUDDER_TOKEN` for automation. `--json` is intended for machine-readable
output.

The old Python CLI and generated Python SDK were retired in Phase 9.
