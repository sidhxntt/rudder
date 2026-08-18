# Phase 9: the operator CLI

> **Status:** Node/TypeScript CLI functionality, shared authorization handoff, status views, log contracts, and focused parity/security fixes are implemented and tested. Full browser-auth and live web-to-CLI acceptance remain environment-dependent exercises.

## Goal

Phase 9 turns `rudder` into a first-class terminal client of the same control plane as the dashboard—not an SSH/Docker/kubectl bypass. It supports a guided TTY flow for humans and strict flags/JSON/exit codes for automation.

## Architecture

The Node 20 + TypeScript package uses Clack only as a presentation/input adapter. Command services call one typed API client; no command speaks directly to Docker, Kubernetes, Terraform, agents, or the database. This preserves reconciliation, authorization, auditability, and identical state between web and CLI.

The interactive launcher has branded splash/context selection and actions for deploy, status, logs, services, variables, advisor and sign-out. No-argument invocation starts it only in a TTY; `--json`, `--no-interactive`, and non-TTY use never open prompts. User cancellation raises the shared cancellation error and exits 130; missing non-interactive input is usage exit 2; normal API/runtime failure is 1.

Authentication uses a short-lived, opaque, single-use backend authorization handoff: CLI creates a handoff, opens/prints the GitHub authorization URL, browser OAuth completes it, and CLI consumes a normal bearer token. The browser never returns that token to the page. The local config holds endpoint/context and interactive token; `RUDDER_TOKEN` is the process-local CI alternative and is not saved. Logout removes only local CLI credentials.

## Operator contracts

Commands map projects, environments, GitHub import, services/graph, variables, deployments/history, rollback, build/runtime logs, operations, analytics, settings and advisor functions to documented APIs. Ambiguous names fail with candidate IDs; explicit IDs/flags win over saved context. Destructive TTY operations name their target, while automation requires `--yes`.

`--json` emits one JSON value to stdout and sends human progress/errors to stderr. Followed logs emit JSON Lines with `timestamp`, `source`, `level`, and `message`; non-follow mode is a completed snapshot. Status has compact deterministic, detailed raw, and optional safe AI-summary views, all with a Back choice in the launcher. The AI snapshot strips variables, image tags, commands, container IDs and raw logs.

## Challenges and fixes

The initial status command printed enormous deployment JSON; the view split gives operators a compact overview without weakening automation. Browser opener processes can neither exit nor error, so the CLI uses a bounded settle timeout before polling handoff status. Workspace URL parsing rejects malformed/non-absolute origins and maps local 8000 API origins to local 3000 web origins. The graph preserves explicit Compose owner relationships, and health counts are not fabricated where no release exists.

The main security lesson is that terminal convenience must not disclose tokens or write-only variable values. The CLI masks values, redacts error paths, never prints auth headers, and makes login state explicit. A future hardening step is OS credential-store storage instead of a sensitive config file.

## Cost and cloud consequences

The CLI itself is local and has no material cloud cost. Its API calls, log streaming, analytics and optional AI summaries consume the same control-plane, cluster, storage, GitHub, and model resources as the dashboard. By avoiding direct cloud runtime calls, it does not create a second IAM or egress surface.

## Verification and known limits

Automated CLI checks cover test suite, TypeScript typecheck/build, cancellation, JSON/stream contracts, status formatting, URL handling, and shared auth behavior. A live acceptance should authenticate through GitHub, prove a web-created project appears in CLI, create/delete a unique project through CLI and observe it in web, run import/deploy/log/rollback, and ensure CI mode never prompts. The source contract and commands are summarized here.
