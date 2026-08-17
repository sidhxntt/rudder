# Interactive Rudder CLI authentication and launcher

## Purpose

Running `rudder` with no subcommand becomes the normal operator entry point.
It should look and feel like a guided terminal application: a clear splash,
one focused decision at a time, graceful cancellation, and a persistent main
menu. Scriptable subcommands and `--json` remain unchanged.

## Interaction model

`rudder` in an interactive TTY clears the terminal, renders an emerald Rudder
mark and a compact control-plane status line, then checks credentials.

1. With a valid saved token, it opens the launcher.
2. Without one, it renders **Sign in with GitHub**, opens the same GitHub OAuth
   authorization URL used by the browser console, shows a Clack spinner while
   waiting, and persists the normal issued bearer token only after success.
3. A cancellation, expired handoff, or browser refusal leaves no credential
   behind and returns a clear retry message.
4. The launcher lets the operator choose or change project/environment, then
   choose Deploy, Status, Logs, Services, Variables, Advisor, or Sign out.
5. Every selected action calls the existing resource command/API path; the
   launcher owns no deployment, runtime, or business logic.

The visual language takes the useful parts of `macos_automations/Git-it-Done`:
terminal reset before a focused flow, a high-contrast branded intro, progress
spinners, concise grouped state, and a positive completion message. Rudder
uses its own dark/emerald identity, monospace topology/status details, and no
emoji-dependent meaning.

## Shared authentication contract

The web and CLI must use one GitHub OAuth implementation. A generic,
short-lived authorization handoff is added to the existing auth router:

```text
CLI                    Control plane                GitHub / browser
 | POST /auth/authorizations ----------------------> |
 | < handoff id + authorization URL                 |
 | open URL -------------------------------------------------> |
 |                                    <--- OAuth callback --- |
 | POST /auth/authorizations/{id}/consume ----------> |
 | < existing JWT access token                       |
```

- The handoff is generic authorization state, not a CLI resource; a future
  native app could use the same contract.
- It is opaque, expires after five minutes, and can be consumed exactly once.
- The browser never receives the Rudder bearer token for this flow.
- The normal web OAuth flow remains cookie-based and redirects to the
  dashboard exactly as it does today.
- `RUDDER_TOKEN` remains the non-interactive alternative. `--no-interactive`
  never opens a browser or prompts.

## Architecture

- `control-plane/rudder_cp/services/authorization_handoff.py`: short-lived
  authorization lifecycle with create, complete, consume, expiry and
  single-use rules.
- `control-plane/rudder_cp/routers/auth.py`: generic unauthenticated start and
  consume endpoints; existing callback completes a handoff only when its
  signed OAuth state contains one.
- `cli/node/src/github-login.ts`: opens the returned authorization URL and
  polls the generic consume endpoint. It receives an ordinary token and uses
  the existing `ApiClient` thereafter.
- `cli/node/src/launcher.ts`: Clack splash, selection menus and a thin adapter
  to existing command functions. It must not reimplement API mutations.
- `cli/node/src/index.ts`: dispatches no-command interactive TTY invocation to
  the launcher. Explicit commands preserve their current behavior.

## Safety and failure behavior

- Browser opening failure prints the authorization URL as a copyable fallback.
- Ctrl-C and prompt cancellation use Clack cancellation output and leave the
  config untouched.
- The launcher confirms destructive operations through existing confirmation
  behavior.
- No token is printed to stdout, logs, menu labels, or `--json` output.
- Unknown/expired/reused handoff IDs produce the standard authenticated API
  error envelope and no token.

## Verification

1. Backend tests prove create → callback completion → one successful consume →
   rejected second consume and expiry.
2. CLI tests prove a no-command interactive TTY dispatches to the launcher,
   browser login saves a token, and non-interactive mode refuses to prompt.
3. Existing explicit command tests prove `rudder project list --json` and
   `RUDDER_TOKEN` continue to work without launcher output.
4. A live local check runs `rudder`, completes GitHub sign-in in the browser,
   selects an existing project/environment, queues a deployment, and verifies
   the same deployment in the web console.

## Acceptance criteria

- `rudder` alone gives a guided, branded interactive flow.
- First interactive launch without a credential begins GitHub sign-in.
- Web login behavior is unchanged.
- The handoff is short-lived, opaque and one-time.
- The CLI’s post-auth actions use only existing control-plane resource APIs.
- All explicit and non-interactive CLI modes remain script-safe.
