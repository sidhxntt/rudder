# CLI Project Onboarding Design

## Goal

After a GitHub sign-in, Rudder must establish a project context before showing
operational commands. An operator either selects an existing project or creates
one through the same GitHub import workflow used by the web workspace.

## User flow

1. `rudder` starts with the existing splash screen.
2. An unauthenticated operator selects **Sign in with GitHub** and completes
   the existing one-time browser authorization handoff.
3. If no project is selected in the local CLI context, the CLI shows:
   - an existing-project choice for every API project;
   - **Create new from GitHub**; and
   - **Exit**.
4. Selecting an existing project saves its project ID. The CLI prompts for an
   environment only when that project has more than one environment; otherwise
   it selects its only environment. It then opens the normal operational menu.
5. Selecting **Create new from GitHub** runs the API-backed equivalent of the
   web import dialog: choose a GitHub installation, repository, branch, and
   optional reviewed template; inspect the server preview; select proposed
   add-ons and public web services; explicitly confirm; then poll import
   progress until Rudder returns a project and environment ID. Those IDs become
   the saved CLI context before the normal launcher opens.

## Architecture

The CLI remains a thin client. It uses the existing authenticated endpoints:
`/projects`, `/github/import/installations`, `/github/import/repositories`,
`/github/import/branches`, `/github/import/templates`,
`/github/import/preview`, `/github/imports`, and `/github/imports/{id}`. It
does not create an alternate project model or control-plane route.

A dedicated `github-import-wizard.ts` module owns only prompt sequencing and
typed API payloads. `index.ts` owns durable CLI context and connects the wizard
to the launcher. `launcher.ts` owns the project-first gate and keeps its normal
operational menu unchanged.

## Cancellation and failures

Every prompt accepts cancellation without persisting a partial context or
creating a project. API errors are surfaced by the existing CLI error path.
Confirmation is required immediately before `POST /github/imports`. The import
polls only after a successful creation response; if a step fails, the CLI shows
the failure status and leaves the created project context available for web or
CLI inspection.

## Test boundaries

Unit tests prove the project-first launcher ordering, existing project context
selection, exact import endpoint request sequence, cancellation without config
writes, and imported project/environment persistence. Existing backend import
tests remain the source of truth for provisioning behaviour.
