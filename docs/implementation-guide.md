# Engineering Implementation Guide

This page is additive: it complements Rudder's phase narrative, architecture,
features, operations, and engineering-challenges pages. It maps each shipped
feature to the code that implements it, the boundary that performs the work,
its safety/authority rules, and the tests that make its contract repeatable.

## Source-to-feature map

| Capability | Principal code | Operator route and evidence |
| --- | --- | --- |
| Control-plane API and data model | `control-plane/rudder_cp/main.py`, models, schemas, routers | Web and CLI use the same authenticated REST API; API/CRUD tests |
| Authentication and ownership | `security.py`, `services/auth.py`, `routers/auth.py`, `services/ownership.py` | password/JWT/GitHub OAuth and resource ownership tests |
| GitHub import and source detection | `services/github_app.py`, `github_oauth.py`, `detect.py`, `compose.py`, `imports.py` | import dialog/CLI wizard and import tests |
| Desired state and deployments | project/environment/service/domain/deployment services | canvas/API/CLI plus deployment, locking, health, rollback tests |
| Local runtime agent | `agent/rudder_agent/main.py`, `docker_ops.py`, `control_plane_client.py` | authenticated agent API and Docker integration tests |
| Kubernetes/GKE runtime | `runtime/kubernetes.py`, `runtime/targets.py`, GCP Terraform and platform manifests | Kind/GKE contract, bootstrap, and Terraform tests |
| Operations and reconciliation | worker, scheduler, reconciler, monitor, operations, metrics, logs | operations panel/CLI, reconciler and runtime-log tests |
| Web workspace | `web/app/`, `web/lib/api.ts`, `web/lib/queries.ts` | component and interaction tests |
| Terminal interface | `cli/node/src/` | CLI unit tests; same API client, never direct infrastructure calls |
| Advisor and Ask Rudder | advisor/assistant routers and services | read-only proposal/diagnostic/assistant tests |
| GitHub automation | webhook router, PR environment and notification services | webhook, PR preview, idempotency, and outbox tests |
| Backup and data boundaries | backup broker, CloudNativePG, variables and security services | identity/backup/variable tests |

## 1. The control plane: desired state is the source of truth

`main.py` creates the FastAPI application, wires its lifespan, routers,
database session dependencies, and background work. SQLModel/SQLAlchemy models
under `models/` represent projects, environments, services, variables,
domains, deployments, instances, nodes, operations, GitHub imports, metrics,
authorization handoffs, and PR notifications. Pydantic schemas under
`schemas/` make the API contract explicit instead of exposing ORM objects.

Routers are intentionally thin authority boundaries. `projects.py`,
`environments.py`, `services.py`, `variables.py`, `domains.py`,
`deployments.py`, `operations.py`, `imports.py`, `nodes.py`, `logs.py`,
`advisor.py`, `assistant.py`, `auth.py`, and `webhooks.py` validate a
request and current user, then delegate state transitions to a service. The
matching services enforce parent ownership, unique names, allowed transitions,
and runtime-specific constraints. That separation means a web click, CLI
command, GitHub webhook, or background worker cannot each invent a different
deployment rule.

Alembic migrations preserve the evolution of the desired-state contract:
initial resources, GitHub import metadata and Compose graph, operation
idempotency, managed service capabilities, PR environment uniqueness, metrics,
GitHub identity, authorization handoff, heartbeat-generation fencing, and the
PR-ready outbox. Migration-chain tests ensure a fresh database and an upgraded
database describe the same operational model.

## 2. Identity, authentication, secrets, and ownership

`security.py` hashes/verifies passwords and issues/decodes bounded-lifetime
JWTs. `services/auth.py` owns seed-admin, password, and GitHub identity
resolution. `routers/auth.py` turns that into browser cookie, API-token, and
one-time authorization-handoff routes. The Node CLI uses the handoff rather
than asking the terminal to duplicate a web password flow.

`services/ownership.py` and the resource services require that a user owns
the project/environment/service before reading or mutating it. Node enrollment
is different: `routers/nodes.py` authenticates the agent with the dedicated
agent secret, receives signed-up/heartbeat state, and fences stale heartbeats
by generation. Variables are stored through `services/variables.py` and are
kept out of ordinary response/log representations. `config.py` rejects
insecure mandatory configuration rather than making a weak development default
look production-safe.

GitHub OAuth is an identity flow in `services/github_oauth.py`; GitHub App
installation/repository access is a separate repository-access flow in
`services/github_app.py`. They are deliberately not conflated. The auth,
app-auth, ownership, variables, GitHub OAuth migration, and builder-auth test
families exercise those differences.

## 3. From repository to reviewed service graph

The import path is a review-first pipeline:

```text
GitHub installation/repository/branch
  → GitHubAppClient fetches permitted repository data
  → detect.py identifies supported source signals
  → compose.py normalizes a supported Compose graph
     or generates a conservative starter plan
  → imports.py provisions reviewed project/environment/services/variables
  → deploy service schedules the same normal deployment lifecycle
```

`GitHubAppClient` mints installation-scoped access and lists only repositories
available to the selected installation. `detect.py` recognizes supported
language/frontend signals. `compose.py` parses and validates Compose services,
roles, ports, volumes, dependencies, public exposure, starter templates, and
managed add-ons. It rejects unsupported/ambiguous constructs rather than
quietly altering a repository's semantics.

`imports.py` persists the accepted plan, creates deterministic project and
service names, records import progress, and can provision managed Postgres or
Redis templates plus their generated internal variables. It makes source
detection a proposal; it does not deploy or expose a service before the
operator confirms it. `builder.py` then clones a resolved commit, selects a
controlled Dockerfile template where appropriate, builds locally or through
Cloud Build, scrubs sensitive text from logs, and preserves an image digest as
the deployable identity.

The web `github-import-dialog.tsx`, `compose-lifecycle.ts`, and advisor
surface show the plan before acceptance. The Node
`github-import-wizard.ts` drives the same API in a terminal. Compose, detect,
import planner/provisioning, GitHub import API, migration, and builder tests
verify the path without requiring a live GitHub installation.

## 4. Deployment: intent, locks, health, promotion, and rollback

A deployment record is created through `routers/deployments.py` and the
deployment service. `services/deploy.py` acquires a per-service advisory lock
from `services/locks.py`, resolves the selected revision/image and runtime,
creates the release, observes health, and only promotes a new public route
after a healthy outcome. It supersedes older releases in a defined order and
drains/discards old replicas only after the replacement is viable.

A failed deployment calls the failure path without discarding the previously
live release. `services/rollbacks.py` restores an immutable earlier deployment
and its public-route target. `services/domains.py` distinguishes a stable
service domain from a deployment-pinned release domain: stable names advance
with the live release; a pinned name remains evidence of a particular build.
Naming validation, same-environment checks, and uniqueness rules prevent one
service from quietly claiming another environment's route.

`services/health.py` waits for the declared readiness result and checks that a
reported container is still alive. `services/nodes.py` and `scheduler.py`
account for node availability/capacity; a runtime node reports facts, while
the control plane owns scheduling policy. Deployment, API, scheduler, health,
locking, runtime-deletion, domain, and rollback tests cover the safety paths.

## 5. The local Docker agent and multi-host runtime

The agent is a small authenticated aiohttp service, not a second control plane.
`agent/rudder_agent/main.py` exposes health, create/get/delete, probe,
runtime-log, metric, Compose up/down/ps endpoints and runs a heartbeat task.
Its middleware authenticates requests from the control plane. Its
`ControlPlaneClient` reports node capacity and heartbeats; it does not choose
which project should run.

`DockerOps` in `docker_ops.py` is the only Docker SDK boundary. It creates
container specs, names/releases/network attachments, validates state, probes
TCP/HTTP health, collects logs/metrics, translates Docker errors, and runs
Compose subprocesses. `schemas.py` shares typed request/response contracts
with the control-plane client. This lets `AgentClient` in the control plane
speak a narrow HTTP protocol rather than importing Docker behavior into the
web API.

The deployment service uses the agent for local Docker releases and keeps
capacity/reconciliation in the control plane. `monitor.py` compares recorded
instances with agent observation; `reconciler.py` performs bounded desired-vs-
actual repair; `worker.py` drives background tasks. Agent create/delete/
inspect/health/runtime-log/Compose tests and control-plane reconciler/monitor
tests prove both halves independently.

## 6. Kubernetes, Kind, GKE, and persistent data

`runtime/kubernetes.py` translates Rudder's service graph into a portable
resource contract: namespace, Deployment or StatefulSet, Service, ConfigMap/
Secret references, Ingress, NetworkPolicy, HPA, PodDisruptionBudget, CronJob,
Job, resource limits, and runtime logs/metrics. `KubernetesRuntime` owns
apply/read/delete behavior through the `KubernetesApi` protocol; the
asynchronous client is the production implementation and fakes keep resource
shape tests fast.

`services/kubernetes_namespace.py` creates one namespace per environment.
Defaults are private: internal services use ClusterIP/DNS discovery, public
routes are explicit, and network policy is default-deny before required traffic
is opened. `runtime/targets.py` derives runtime settings and the Kubernetes
client from configuration rather than making GCP data part of a project model.
Kind bootstrap/configuration proves the contract locally.

GKE is an implemented infrastructure path with explicitly bounded evidence.
The Terraform under `infra/gcp/terraform/` creates the shared landing zone:
network, cluster, registry, identity, DNS, monitoring, storage, services, and
outputs. Kubernetes platform manifests install ingress, cert-manager,
external-dns, External Secrets, CloudNativePG, migration, RBAC, and control
plane resources. Bootstrap/preflight/verification scripts make setup
repeatable. GKE remains single-tenant learning infrastructure; AWS/Azure are
documented mappings, not deployed adapters.

CloudNativePG is represented by the runtime's Postgres and backup spec types.
`backup_broker.py` and `runtime/backup_identity.py` constrain backup
identity issuance so a workload receives only its intended cloud identity.
GKE/Kubernetes/Kind, Cloud Build, DNS, backup broker/identity/settings, image,
target, preflight, node-pool, and migration tests verify the contracts.

## 7. Environments, previews, operations, and observability

`services/environments.py` creates/clones/cleans environments. PR webhook
handling creates a capped preview environment from an accepted graph and removes
it on close/merge. A unique PR-environment rule and idempotency keys prevent
duplicate source events from producing duplicate deployments.

`services/operations.py` turns operator requests into normalized desired
intent and durable operation rows. It validates the service kind and managed
capability before accepting scale, restart, rollback, database, or allowed-job
actions. `operation_dispatch.py` queues work; `operation_reconciler.py`
makes pending state converge; `scheduler.py` handles timed work. The UI and
CLI read operation state rather than assuming an HTTP acceptance means runtime
completion.

`logs/store.py`, `logs/runtime.py`, and `logs/sse.py` retain and stream
build/runtime logs with authorization checks. `services/runtime_logs.py`
queries the correct agent or Kubernetes runtime. `services/metrics.py`
collects/compacts time-series runtime metrics; `monitor.py` reconciles
instance projections. `services/pr_notifications.py` uses a durable outbox
with retry for PR-ready comments, so a transient GitHub failure is not silently
lost. Operations, dispatch/reconciliation, logs/authorization/runtime logs,
metrics, monitor, PR-environment, and PR-notification tests cover these paths.

## 8. Web workspace: a canvas backed by real APIs

The Next.js application uses `web/lib/api.ts` as its typed API boundary and
`web/lib/queries.ts` to synchronize resource reads. `session.tsx` maintains
the authenticated browser session; `providers.tsx`, `layout.tsx`, and
`workspace-page.tsx` compose the application shell.

The environment page is a control surface, not a static diagram:
`canvas.tsx`, `service-node.tsx`, and `canvas-edges` render persisted
service topology and navigation; `detail-panel.tsx`/tabs, service settings,
variables, project settings, domains, and deployment history call the resource
APIs. `operations.tsx`, build logs, metrics/sparkline, and status-dot render
asynchronous runtime evidence. The Compose lifecycle and GitHub import dialog
require a reviewed source graph. The advisor node/surface uses ghost proposals
that remain non-mutating until individually accepted.

Interaction tests beside the components validate request shaping, layout,
navigation, detail tabs, variables, operations, logs, import, Advisor, and
session behavior. This prevents a frontend-only implementation from drifting
from control-plane response contracts.

## 9. CLI parity without a second backend

The Node/TypeScript `rudder` CLI is an operator interface to the same API.
`cli/node/src/client.ts` holds API transport/error handling; `context.ts` stores local
connection context with restrictive file permissions; `auth-guard.ts`,
`github-login.ts`, and `launcher.ts` implement the browser authorization
handoff and interactive launcher. `index.ts` parses flags, selects projects,
environments/services/logs, and produces machine-readable error envelopes when
requested.

`github-import-wizard.ts`, `graph.ts`, `status.ts`, `advisor.ts`,
`command-target.ts`, and `output.ts` provide import, topology, status,
advice, command routing, and human/JSON output. It deliberately does not call
Docker, Kubernetes, Terraform, or GCP directly: authorization, ownership,
operations, health, and audit semantics stay in one backend. CLI client,
context, auth, launcher, command-target, graph, status, import, and advisor
tests cover both interactive and automation paths.

## 10. GitHub automation and read-only AI assistance

`routers/webhooks.py` verifies GitHub webhook HMAC before processing an event.
Push events queue the same deployment machinery as manual deploys; pull-request
events use the preview lifecycle. The handler uses event identity/idempotency
rules and the durable notification outbox. No webhook can bypass ownership,
reviewed import state, or normal deployment/health promotion.

`services/advisor.py` scans a checked-out repository for supported signals
and returns reviewable service/relationship proposals. The API only accepts a
proposal through ordinary resource writes. Build diagnosis evaluates saved
evidence. `services/assistant.py` builds a redacted, owned-environment
context and rejects action-shaped requests before optional OpenAI completion.
`routers/advisor.py` and `routers/assistant.py` are read-only analysis
routes; neither is a deployment executor. Advisor, assistant, API, and
authorization tests make the human-acceptance boundary explicit.

## Verification map and evidence boundary

| Layer | Main checks |
| --- | --- |
| Control plane | FastAPI CRUD/auth/import/deploy/domain/variable/operation/reconciler/scheduler tests |
| Agent | create, delete, inspect, health, logs, Compose, and executor tests |
| Runtime | Docker/Kind/Kubernetes/GKE/Cloud Build/backup/DNS/image/target contract tests |
| Web | Vitest component and API/session synchronization tests |
| CLI | TypeScript client/auth/context/launcher/status/graph/import/advisor tests |
| Documentation | renderer, phase evidence, configuration, operations, architecture, and this guide |

Run the component-appropriate test command from its directory; external cloud,
GitHub App, DNS, and GKE work also requires the documented credentials and
controlled acceptance procedure. A passing fake-runtime test proves a contract,
not that every cloud integration is live. The Phase 4 evidence record and
phase documents state the strength and date of real-environment evidence.

## Keeping this guide honest

For a new feature, add: the operator action and desired-state model; the router
and service that authorize it; the runtime/provider boundary that executes it;
the health, rollback, permission, or failure behavior; and the exact test or
evidence record. Additive documentation belongs here alongside the phase
narrative—never replace an existing phase, evidence record, or operational
runbook with a high-level summary.
