# Phase 9 — Operator CLI parity

**Target:** 2–3 weeks

**Demo:** from a terminal, authenticate through Rudder's shared GitHub browser
authorization handoff, import a repository, inspect its
service graph, deploy it, follow coloured logs, change an operation, inspect
analytics, and restore an earlier release — with the same resulting state as
the web console.

**Outcome:** `rudder` becomes the terminal client for the whole product. It is
not a second control plane, an SSH wrapper, or a shortcut around the API. Every
CLI command maps to the same authenticated control-plane resource and mutation
that the web console uses. An operator gets an excellent guided experience in a
TTY; a script gets stable flags, JSON, exit codes, and no prompts.

## Current launcher (local implementation)

The local Node CLI now provides a GitHub-authenticated interactive launcher.
Running `rudder` with no arguments from a TTY starts it; it does not attempt to
launch in a non-TTY, with `--no-interactive`, or with `--json`.

On the first interactive use, the CLI requests a short-lived authorization URL
from the shared Rudder backend, opens that URL in a browser, and waits for the
same backend handoff to return an access token. The browser flow authenticates
with GitHub. If the browser cannot be opened, the CLI prints the URL for manual
opening. This is shared backend authentication, not a CLI-specific control
plane or a claim of browser/terminal state synchronization.

After authentication, a first-run launcher does not expose operational actions
until the operator selects an existing project or chooses **Create new from
GitHub**. Existing projects receive their production/default environment as
the initial context (shown as `development` on localhost, matching the web).
Creating a project uses the same reviewed GitHub import API sequence as the
web: source/template, GitHub connection, repository, branch, detected release,
private add-ons, public web services, and an explicit deploy confirmation. The
created project and environment become the saved local context. Only then does
the menu offer deploy, status, logs, services, variables, advisor, sign-out,
and exit. Selected targets can later be changed or overridden with `--project`,
`--env`, and `--service`.

For local verification:

```bash
cd cli/node
npm install
npm link
rudder
```

`npm link` exposes the local `rudder` binary; it neither publishes the package
nor pushes Phase 9 changes.

The saved CLI URL, access token, and selected context are stored by default in
`~/.config/rudder/config.json` (or the path in `RUDDER_CONFIG`). The file is
sensitive because it holds the access token. `rudder logout` removes that local
token but retains the URL and context; it does not remotely revoke a GitHub or
backend session.

Automation supplies a process-local token and disables prompts explicitly:

```bash
RUDDER_TOKEN=... rudder --no-interactive project list --json
```

With `--no-interactive`, browser sign-in and prompts are refused. A
non-TTY command also cannot prompt, but an authenticated command may use either
an already-saved CLI token or `RUDDER_TOKEN`; prefer `RUDDER_TOKEN` for CI.
Bare `rudder` in a non-TTY prints usage rather than opening the launcher.

---

## Current baseline

The existing Python/Typer CLI was the Phase 1 thin wrapper. It covers basic
projects, environments, services, variables, deployments, status, and logs,
but it does not cover GitHub import, Compose topology, release history,
rollbacks, operations, analytics, settings, or the Phase 8 advisor. It also
does not provide the interactive terminal experience required here.

Phase 9 replaces that shell with a Node 20 + TypeScript CLI using
[`@clack/prompts`](https://www.npmjs.com/package/@clack/prompts). The existing
REST API, resource schemas, and control-plane reconciliation remain the source
of truth. The implementation may retire the old Python entry point only after
the parity acceptance suite passes; it must not run two independently evolving
CLIs under the `rudder` command.

## Invariants

- **API parity, not UI imitation.** The CLI exposes every operator capability
  from the web console, but it does not attempt to reproduce canvas dragging or
  charts as terminal art. It presents the same resources and mutations in a
  terminal-appropriate form.
- **One control plane.** The CLI never calls Docker, `kubectl`, Terraform,
  BuildKit, the node agent, or the database directly. If an action cannot be
  performed through a documented API, Phase 9 adds the API first and then both
  clients consume it.
- **Interactive and automatable are equal modes.** A TTY without enough flags
  starts a Clack flow; `--no-interactive` refuses to guess. Every completed
  command has explicit flags and `--json` for CI and other programs.
- **No secret disclosure.** Variables remain write-only. Tokens never appear in
  normal output, JSON, error messages, or shell history. The current launcher
  stores its interactive access token in the documented local config file;
  `RUDDER_TOKEN` is a process-local automation credential and is never saved.
  Moving interactive credentials to an OS credential store remains a Phase 9
  hardening requirement.
- **Safety is consistent.** Destructive actions always show the exact affected
  resource in a TTY confirmation. Automation must pass `--yes`; no global
  `--force` exists.

---

## CLI contract

### Package and command architecture

`cli/` becomes a TypeScript package with Node 20 as its supported runtime.
`src/client/` is the only HTTP boundary and is generated or mechanically
derived from the control-plane OpenAPI contract. `src/commands/` contains small
resource-oriented command modules. A shared command service accepts a validated
input object and returns typed data; Clack is only the interactive input/output
adapter, so a prompt path and a flag path cannot implement different behavior.

```text
TTY prompts / flags / --json
            │
      typed command service
            │
       OpenAPI API client
            │
     Rudder control-plane API
            │
  reconciler → agents / Kubernetes runtime
```

Human-readable tables, spinners, progress updates, prompts, and diagnostics go
to stderr. `--json` writes exactly one documented JSON value to stdout; streamed
logs use one JSON object per line. This makes pipes reliable while retaining a
pleasant terminal experience.

### Authentication and context

`rudder login` starts the shared `POST /auth/authorizations` browser handoff
and consumes its resulting bearer token; GitHub authentication remains in the
browser. The CLI does not create a CLI-only OAuth callback or control plane.
`RUDDER_TOKEN` is the process-local automation alternative and is preferred in
CI; non-interactive commands may also use an already-saved CLI token. `rudder
whoami` uses the same identity endpoint as the web client, while `rudder
logout` clears only the CLI's locally saved token.

The CLI keeps a non-secret selected project, environment, and service context.
An explicit UUID or flag always wins over context; an ambiguous name is an
error that prints candidate IDs. `--project`, `--env`, and `--service`
work on every relevant command. Context selection is a convenience, never an
implicit mutation target in non-interactive mode.

### Command map

| Web-console capability | Interactive CLI | Automation contract |
|---|---|---|
| Authentication and account | `rudder login`, `rudder whoami`, `rudder logout` | `RUDDER_TOKEN`, `rudder whoami --json` |
| Projects and environments | `rudder project`, `rudder environment` guided create, rename, clone, select, delete | explicit subcommands, IDs/flags, `--yes` for delete |
| GitHub import | `rudder import github` repository → branch → Compose/add-on review | `rudder import github --installation ID --repo OWNER/REPO --branch main --json` |
| Canvas topology | `rudder service graph` renders a labelled release tree and ownership links | `rudder service graph --json` returns nodes and edges |
| Services and service settings | `rudder service create/list/show/rename/delete/settings` | flags for image/source, resources, domain, health, and settings |
| Variables | `rudder variable set/list/remove` with masked confirmation | key/value flags; values never returned, even with `--json` |
| Deployments and rollback | `rudder deploy`, `rudder deployment history`, `rudder rollback` | deployment/service IDs, `--follow`, `--yes`, JSON state |
| Build and runtime logs | `rudder logs --build` and `rudder logs --runtime` with level colours | `--json --follow` emits timestamped JSON Lines |
| Operations | `rudder operation resources/autoscaling/topology/observability` | explicit desired-state flags and idempotency key support |
| Analytics | `rudder analytics service` renders compact metric summaries and sparklines | exact sampled series, aggregates, interval, and timestamps as JSON |
| Project/service settings | `rudder project settings`, `rudder service settings` | explicit patches; destructive project removal requires `--yes` |
| Phase 8 advisor | `rudder advise repo` and `rudder advise diagnose` with per-item accept/reject | deterministic proposal/diagnosis JSON; accepts still call normal APIs |

The exact names may be refined for consistency, but the command families and
their parity obligations are fixed. `rudder help` must include both an
operator-first example and its non-interactive equivalent for every family.

### Interaction behavior

Clack flows must be short, reversible, and explicit:

1. List/select only when a required target was not provided.
2. Show the resolved project, environment, service, and pending mutation before
   mutating state.
3. Use `p.cancel()` and exit 130 for a user cancellation; never convert cancel
   into a default selection.
4. Stream deploy/log progress with a final success or failure summary that
   includes the deployment ID and permanent URL when available.
5. Render log levels consistently: `ERROR` red, `WARN` yellow, `INFO` blue,
   `SUCCESS`/healthy green, and unclassified output muted. Colour is disabled
   for non-TTY output or `NO_COLOR`.

`--json` implies `--no-interactive`. A command invoked with missing required
flags in this mode exits with usage status 2 and a machine-readable error when
`--json` was requested. API errors preserve Rudder's `{code, message, details}`
envelope, mapped to documented exit codes: 0 success, 1 runtime/API failure, 2
usage or incomplete non-interactive input, and 130 cancellation.

---

## Execution plan

1. **Establish the TypeScript command foundation.** Create the Node package,
   Clack renderer, argument parser, config/context store, terminal capability
   detection, typed API client boundary, output formatter, and one error/exit
   contract. Preserve the Python CLI only as a migration reference until parity
   tests explicitly replace it.
2. **Add authentication and targeting.** Use the shared browser authorization
   handoff and consume its bearer token. Persist the interactive token, Rudder
   URL, and selected context in the documented local config file until OS
   credential-store hardening lands; support the process-local `RUDDER_TOKEN`
   automation token, explicit-ID resolution, and consistent
   project/environment/service selectors. The CLI remains a client of the
   shared control plane, not a separate CLI control plane.
3. **Port foundational resources.** Implement projects, environments, service
   lifecycle, variables, domains, GitHub import, and a textual service graph.
   The import wizard must show the exact Compose release that it will confirm.
4. **Port delivery observability.** Implement deploy, immutable release
   history, deployment-pinned URLs, rollback confirmation, build logs, runtime
   logs, and terminal-safe follow mode.
5. **Port operations and settings.** Add resources, autoscaling, topology,
   observability, service settings, project settings, rename, and guarded
   deletion. All commands must surface the current observed/desired state
   rather than suggesting local-only success.
6. **Port analytics and the advisor.** Render useful TTY summaries without
   inventing metrics; return raw sampled values via JSON. Expose the Phase 8
   proposal and diagnosis flows without giving the advisor any mutation path
   beyond the same explicit resource commands used elsewhere.
7. **Retire the old command surface deliberately.** Publish migration notes,
   compatibility aliases only where semantics match exactly, and one end-to-end
   parity fixture that performs the same actions through web/API/CLI and
   compares resulting resources.

## Where this goes wrong

**A direct runtime escape hatch.** A tempting `rudder kubectl` or local Docker
shortcut makes the terminal more powerful than the console and bypasses desired
state, auditability, and reconciliation. Keep it out.

**Prompts that make automation impossible.** A spinner or selection prompt
must never contaminate stdout JSON or block a CI job. All prompts are opt-in
TTY behavior; flags and `--no-interactive` always remain complete.

**Two semantics for the same operation.** If an interactive wizard applies a
different default, validates differently, or omits an idempotency key used by
the flag path, the CLI is already two products. Both adapters call one typed
command service.

**Leaking values or tokens through convenience output.** Do not add a
`variable get`, echo entered variable values, include authorization headers in
debug traces, or serialize credentials in JSON. Redaction happens before any
formatter sees an error.

**Treating a terminal graph as authoritative topology.** The graph displays
control-plane relationships; it cannot claim network traffic or hidden runtime
dependencies. Relationship labels use the same truthful semantics as the web
canvas.

**Replacing raw logs with colourful summaries.** Colour improves scanning, not
truth. The original log line, timestamp, source, and level remain available,
and a failed follow command exits non-zero only after the deployment reaches a
terminal failed state.

---

## Verify

```bash
# Package quality
cd cli/node
npm test
npm run typecheck
npm run build

# Machine-readable output is one JSON value and never contains Clack chrome.
rudder --no-interactive project list --json | jq -e 'type == "array"'

# Interactive smoke test (TTY): `rudder` starts the shared GitHub browser
# handoff, and choosing a project/environment saves the selected local context.
rudder

# Web ↔ CLI shared-state proof: create a project named `cli-sync-check` in the
# web dashboard, then confirm it is immediately visible in the CLI. Create a
# second uniquely named project through the CLI, reload the web dashboard, and
# confirm it appears there too. Delete only that second test project through
# the CLI with --yes, reload the dashboard, and confirm it disappears.
rudder project list --json | jq -e '.[] | select(.name == "cli-sync-check")'
rudder project create cli-created-sync-check
rudder project list --json | jq -e '.[] | select(.name == "cli-created-sync-check")'
rudder project delete cli-created-sync-check --yes

# API parity fixture: execute the same import → deploy → logs → rollback flow
# through the CLI and compare resources fetched from the control-plane API.
cd ../control-plane
uv run pytest tests/test_cli_parity.py -q

# Logs remain script-safe and terminal-friendly.
rudder logs app --build --follow --json | jq -c '.level and .message'
NO_COLOR=1 rudder logs app --build --follow

# Safety checks: no prompt-free destructive action and no variable secret read.
rudder --no-interactive project delete PROJECT_ID; test $? -eq 2
rudder variable get DATABASE_URL; test $? -ne 0
```

## Done when

- [ ] `rudder` is a TypeScript/Node 20 CLI using Clack; the legacy Python
  entry point is retired or an explicit, tested compatibility shim.
- [ ] Every web-console operator capability through Phase 8 has a CLI command
  with documented interactive and non-interactive forms.
- [ ] CLI mutations use only the same control-plane API resources as the web
  console; no direct Docker, Kubernetes, database, or agent mutations exist.
- [ ] Shared GitHub browser authorization, documented local-config persistence
  until credential-store hardening, logout, selected context, and
  `RUDDER_TOKEN` automation authentication work without exposing tokens.
- [ ] The first operational CLI command uses an existing CLI credential or the
  process-local `RUDDER_TOKEN`; non-interactive CI prefers `RUDDER_TOKEN`.
- [ ] Projects created in web are immediately visible in the CLI, and projects
  created or deleted by CLI appear or disappear in web after refresh.
- [ ] GitHub import, service graph, deploy/history/permanent URLs, rollback,
  build/runtime logs, operations, analytics, settings, and advisor flows work
  end to end.
- [ ] `--json` produces stable, prompt-free stdout and streamed output is JSON
  Lines; non-interactive incomplete input exits 2.
- [ ] Destructive operations require an exact interactive confirmation or
  `--yes`; cancellation exits 130 without mutation.
- [ ] Variables remain write-only and no command or diagnostic leaks a token or
  secret value.
- [ ] API-parity and terminal integration tests run against the local Docker
  stack, and the README has install, migration, and demo instructions.
