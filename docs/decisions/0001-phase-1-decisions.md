# ADR 0001 — Phase 1 open decisions resolved as proposed defaults

**Date:** 2026-07-23
**Status:** Accepted

## Context

`PRD.md` → "Open Decisions" listed seven blocking decisions (D1–D6, D15) with a
proposed default each, plus eight silent defaults (D7–D14). Phase 1 could not
start until they were resolved.

## Decision

All seven accepted as written. No objection raised to D7–D14, so they stand.

| # | Resolution |
|---|---|
| D1 | `Service.container_port: int = 8080`. `health_check_port` defaults to it when null. |
| D2 | Single `GITHUB_TOKEN` env var. No `GitHubInstallation` table in Phase 1. |
| D3 | **(b)** — the node agent is built in Phase 1, running on localhost, control plane talks to it over HTTP from day one. |
| D4 | "Logs" in the Phase 1 UI means build logs only. Runtime logs are Phase 5. |
| D5 | Adopt `DESIGN-supabase.md` token scales; invert app-shell surfaces to `canvas-night`; emerald stays the single accent. |
| D6 | DB owns truth. `canvas_x/y` stays, treated as UI-only metadata no declarative layer ever manages. |
| D15 | `Domain` table lands in Phase 1; Traefik config is generated from Domain rows, never from Service rows. |

## Rejected alternatives

- **D3(a)** — isolate Docker calls in `services/runtime.py` shaped like the future
  agent API, introduce the agent in Phase 2. Rejected: it is exactly the
  "interface for later" the Working Agreement bans, and it risks rewriting the
  whole deploy path plus its tests in Phase 2. (b) costs ~4 days now against
  ~1 week later.
- **D5 as written** — the source doc mandates a white canvas and calls it
  non-negotiable. Rejected for the app shell: Rudder is a dense operator console
  with a React Flow canvas, and a white canvas fights both log streams and node
  graphs. The scales transfer; the skin does not.
- **D6 code-owns-truth** — drop `canvas_x/y`, auto-layout the canvas read-only.
  Rejected: drag-to-position is worth keeping and layout is not structure, so
  nothing has to be unwound if a declarative layer lands later.
- **D15 routing keyed on Service** — one hardcoded Traefik router per service.
  Rejected: every downstream feature (instant rollback, branch previews,
  immutable deployment URLs, custom domains) needs many hostnames pointing at
  different Deployments simultaneously. ~1 day now against a routing rewrite later.

## Consequence beyond the decision list

The tokens file (`web/styles/tokens.css`) adds semantic **status colors**
(live / building / failed / draining) that the source design doc does not have
and whose "no additional system colors" rule nominally forbids. That rule is
about decoration on a marketing page. An operator console has to signal state at
a glance, so status colors are added deliberately and restricted to status
indicators.

## Consequence for D7 (host prerequisite)

`buildkitd` runs with `network_mode: service:registry` in `docker-compose.dev.yml`
so that `localhost:5000` resolves to the registry inside buildkitd as well as on
the host. The build push and the runtime pull therefore agree on one tag string.
The documented one-time exception stands: the host Docker daemon needs
`localhost:5000` in `insecure-registries`.
