# Phase 1 — Single-host control plane and safe deployment

> **Evidence status:** implemented and locally accepted on 2026-07-24. This is
> a single-host baseline, not a production multi-node availability claim.

## Objective and delivery plan

Phase 1 proved the smallest useful Rudder loop: create a project and service,
build a repository revision, run it, wait for health, route a hostname to it,
and preserve the old revision when anything fails. The reference stack was
PostgreSQL for control-plane state, BuildKit and a private registry for images,
Traefik for HTTP routing, a localhost Rudder agent for Docker execution, and a
React operator UI.

The plan intentionally did **not** add scheduling, shared private networking,
or cloud orchestration. All components lived on one Docker host. The canonical
design and acceptance evidence are consolidated in this retrospective.

## Design and technical logic

### State first, then asynchronous work

The deploy API creates an immutable `Deployment` in `queued` state and returns
`202`; a background worker builds and deploys it. A browser disconnect cannot
cancel a build because logs are persisted and SSE only tails them. This is the
basic control-plane pattern Rudder keeps throughout the project.

### Build path

Rudder clones the requested Git SHA into a temporary directory. A checked-in
Dockerfile wins; otherwise deterministic heuristics recognise Node, Python, or
Go and choose a checked-in template. BuildKit produces an image tagged from the
service identity and commit. This avoided LLM-generated build instructions in a
safety-critical first release while keeping the path extensible for later
agentic help.

### Safe rollout and routing

A candidate container is created with resolved variables and CPU/memory limits,
then health-checked (default 60 seconds, two-second polling and a startup grace
period). Only a healthy candidate is added to Traefik configuration. The old
instance drains before stopping; a build or health failure marks the deployment
failed and leaves the old route intact. Routing is generated from `Domain` rows,
not hard-coded service names, so several hosts can refer to different releases.

### Product surfaces

The API exposed authenticated CRUD for projects, environments, services,
variables and domains plus OpenAPI. Variables are write-only. The browser UI
used a React Flow canvas, service detail panels, build logs, history, and
deployment controls. A CLI exercised the same REST flow with no browser.
GitHub webhooks use HMAC validation and initiate asynchronous deployments.

## Difficulties and resolutions

| Risk | Resolution |
| --- | --- |
| Two pushes race for the same route | A PostgreSQL advisory lock serialises a service deployment; older non-terminal deployments are superseded. |
| Health succeeds then process dies before routing | Liveness is rechecked immediately before traffic shift. |
| Build-log client disconnects | Logs are stored independently of SSE connections. |
| Docker registry pulls fail as HTTPS/TLS errors | The local registry and Docker daemon insecure-registry requirement is explicit and development-only. |
| Delete leaves containers/routes behind | Runtime teardown and Traefik rendering precede database deletion. |

## Cloud and cost implications

This phase was purposefully local. PostgreSQL, BuildKit, registry, Traefik, and
application containers share one host, so costs are small but failure domains are
also shared. There is no HA, cloud load balancer, durable off-host backup, or
mutually untrusted workload isolation. The practical cost lesson was architectural: exposing
no application host ports lets Traefik route two revisions during rollout,
without buying a larger network product prematurely.

## Evidence

The recorded acceptance deployed both a Node and Python application, tested a
failed Dockerfile without interrupting the old URL, stopped/recovered a live
container, executed a CLI deployment, and used a real signed GitHub webhook.
Two near-simultaneous deployment requests ended as one live and one superseded
deployment. At the recorded acceptance, control-plane tests were 255 passing,
agent tests 50 passing, and web/CLI builds passed.

## Boundaries and handoff

The phase does not prove cross-host failover, runtime log retention, production
TLS, persistent state safety, or a hardened cloud workload boundary. Its key handoff is
the durable desired-state and health-gated-routing contract used by Phase 2 and
the Kubernetes runtime.
