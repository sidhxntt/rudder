# Rudder technical stack

This guide explains the technologies that make up Rudder, what each one does,
and why the project uses it. It is written for a reader who may know what an
application is but has not operated a deployment platform before.

Rudder is not one program that runs every workload itself. It is a
**control plane**: it records what an operator wants (a project, environment,
services, variables, domains, and a release) and asks a runtime to make that
state real. The runtime may be Docker on a laptop or private VM, a set of
Docker-capable worker agents, or Kubernetes. Keeping the user-facing model
separate from the execution engine is the central technical choice behind the
stack.

For an introduction to the product and its architecture, start with
[overview.md](overview.md) and [architecture.md](architecture.md). For the
chronological decisions that introduced each part, use
[the documentation index](index.md).

> **Scope and accuracy note:** GCP/GKE is the implemented production reference
> path. Docker Compose and Kind are supported development/runtime paths. The
> repository describes provider abstractions for AWS and Azure, but it does
> **not** provision EKS or AKS. Likewise, the root README calls the current
> product a single-tenant learning build; per-environment isolation is a real
> runtime boundary, but it should not be represented as a completed
> multi-customer SaaS tenancy system.

## At a glance

| Layer | Primary technology | Responsibility |
| --- | --- | --- |
| Web console | Next.js 15, React 19, TypeScript | Canvas-based operator experience and API client |
| Terminal interface | Node.js 20, TypeScript, Clack | Interactive and scriptable `rudder` CLI |
| Control plane | Python 3.12, FastAPI, Pydantic | API, authentication, desired state, deployment orchestration |
| Durable metadata | PostgreSQL, SQLModel, Alembic | Projects, environments, releases, domains, users, and migrations |
| Local/multi-host execution | Docker, BuildKit, Rudder aiohttp agent | Build images and create/observe containers |
| Kubernetes execution | Kubernetes API, `kubernetes-asyncio` | Namespaces, workloads, services, ingress, policy, logs, metrics |
| Local Kubernetes lab | Kind, Calico, ingress-nginx, MinIO | Reproducible production-shaped acceptance environment |
| GCP production foundation | GKE Standard, Artifact Registry, Cloud Build, GCS, Cloud DNS | Private cluster, immutable supply chain, edge DNS/TLS, backups |
| Infrastructure definition | Terraform, Helm bootstrap scripts, Kubernetes YAML | Versioned cloud baseline and pinned platform add-ons |
| Integrations | GitHub OAuth/App/webhooks, OpenAI Responses API | Login/repository workflow and explicitly read-only assistance |
| Quality controls | pytest, pytest-asyncio, Vitest, TypeScript, Ruff | Unit/API/runtime contracts, CLI/UI tests, static checks |

## 1. Languages and application frameworks

### Python 3.12 for the control plane and node agent

The backend is split into two Python packages:

- `control-plane/` is `rudder-cp`, the API and deployment coordinator.
- `agent/` is `rudder-agent`, the small process that owns Docker state on one
  host in the Docker/multi-host runtime.

Python is a practical fit for this part of the system because the main work is
I/O orchestration: database operations, HTTP requests, webhook processing,
Docker/Kubernetes calls, health polling, and background reconciliation. The
control plane uses asynchronous APIs where waiting is normal; it should not
block the entire server while a build, agent, or Kubernetes API operation is
in progress. Python also has mature clients for PostgreSQL, Docker, and
Kubernetes.

The trade-off is that Python is not the fastest language for CPU-heavy build
work. Rudder deliberately does not compile user applications inside the API
process: BuildKit or Cloud Build does that work. The API is therefore sized as
a coordinator, not a build worker.

### FastAPI and Uvicorn

[FastAPI](https://fastapi.tiangolo.com/) exposes the HTTP API. It supplies:

- typed request and response validation;
- generated OpenAPI documentation during local development;
- dependency injection for current-user authentication and database sessions;
- asynchronous route handlers for runtime and external API calls.

Uvicorn is the ASGI server that runs FastAPI. The separation matters: FastAPI
describes application behavior, while Uvicorn owns the process that accepts
network connections. In production this should sit behind the platform ingress
and receive only the traffic intended for the control plane.

### Pydantic and pydantic-settings

Pydantic validates API schemas and configuration. `pydantic-settings` maps
`RUDDER_*` environment variables to a typed settings object. This protects
against a surprisingly common control-plane failure: accepting malformed
URLs, a negative timeout, a missing required provider value, or non-finite
timing values and discovering the mistake halfway through a deployment.

Configuration is deliberately different by runtime. For example, the Docker
and Kind paths can use a local registry and BuildKit address, while GKE
requires Artifact Registry and rejects local backup credentials. The detailed
inventory is described in [overview.md](overview.md).

### Node.js, TypeScript, and the CLI

The maintained CLI lives in `cli/node/`. Node 20 and TypeScript make it a
natural peer to the browser client: it consumes the same JSON API and benefits
from typed response-shape checks. It intentionally does **not** talk directly
to Docker or Kubernetes. That constraint prevents terminal workflows from
creating a second, unaudited mutation path around the control plane.

[Clack](https://clack.cc/) provides accessible terminal prompts, progress
states, selections, and cancellation behavior. Flags and `--json` output are
kept alongside guided prompts so automation does not have to emulate a TTY.
The CLI is therefore both an operator tool and a CI-friendly API client. See
[Phase 9](phases/phase-9.md) for its parity goal.

### Next.js, React, React Query, and React Flow

The web console in `web/` uses Next.js 15 and React 19. It is a client for the
control-plane API, not a hidden second backend. Its main roles are:

- project and environment navigation;
- a Railway-style service canvas;
- deploy/rollback/operation controls;
- GitHub import and Advisor surfaces;
- release, status, and error visibility.

`@xyflow/react` (React Flow) renders the directed service graph. That choice
is meaningful rather than decorative: a project is represented as services
and dependencies, with canvas positions stored as metadata. React Query owns
request caching, loading/error state, and safe invalidation after mutations.

Next.js/React make a responsive operator interface straightforward, but they
do not make the platform secure by themselves. Every sensitive action must
still be authorized by FastAPI; the API is the security boundary. The UI tests
use Vitest, Testing Library, and JSDOM, while TypeScript catches incompatible
API-shape changes before a browser build.

## 2. Metadata, schemas, and migrations

### PostgreSQL

PostgreSQL is Rudder's durable source of desired state. It stores users,
projects, environments, services, variables, domains, deployments, instances,
nodes, imports, and operational history. Runtime systems are intentionally not
the database of record: a container or Pod can disappear, but the database
still tells the reconciler what should exist.

PostgreSQL was chosen rather than a document store because the platform needs
transactional updates and relationships: a service belongs to one environment,
an environment belongs to a project, a deployment is tied to a service and
its immutable image, and authorization must follow those relationships. A
relational database also makes uniqueness, foreign keys, and carefully scoped
queries enforceable.

### SQLModel, Psycopg, and Alembic

SQLModel provides typed data models and SQLAlchemy-style querying; Psycopg is
the PostgreSQL driver. Alembic migrations are versioned, ordered database
changes. This is important for a platform: adding an in-memory Python field is
not enough when an existing deployment database also has to understand it.

Migrations are tested as a chain, including forward and downgrade concerns
where relevant. They make upgrades reproducible instead of relying on a manual
operator to edit a live database. SQLite/injected fakes make the ordinary test
suite fast; real PostgreSQL acceptance checks are still required for behavior
that depends on PostgreSQL semantics.

## 3. Security and identity components

### Passwords, sessions, and encrypted values

The backend uses `passlib[bcrypt]` for password hashing, `PyJWT` for signed
session tokens, and `cryptography`/Fernet for encrypted variable values. The
intent is separation of concerns:

- a password is one-way hashed, not recoverable;
- a session token proves a signed login for a limited period;
- a deploy-time secret may be decrypted only by the control-plane path that
  needs to create a runtime secret or environment.

Key material must come from secret-managed environment configuration, never
from source code or browser-public frontend variables. Fernet supports a key
rotation list: retain an old key during migration, write new values with the
first key, then remove old keys only after re-encryption/retirement planning.

There is a deliberate temporary dependency constraint: `bcrypt` is pinned
below 5 because the currently used `passlib` release probes bcrypt in a way
that bcrypt 5 rejects. This is recorded in `control-plane/pyproject.toml`; it
is a maintenance item, not a claim that the pin is ideal forever.

### GitHub OAuth, GitHub Apps, and signed webhooks

These are separate integrations with separate credentials:

1. **GitHub OAuth** authenticates a person into Rudder.
2. **GitHub App** tokens enumerate approved installations/repositories and
   clone private source with scoped repository access.
3. **Webhook secret validation** verifies that an inbound push or pull-request
   event came from GitHub.

Keeping them separate limits blast radius. A user-login OAuth credential
should not become a broad deployment credential; an App private key should be
mounted read-only or retrieved from secret management; unsigned webhooks must
never queue releases. Browser handoff/authorization records are bounded and
consumed atomically to avoid indefinite polling or token reuse.

### Kubernetes identity and authorization

On GKE, Workload Identity connects a Kubernetes ServiceAccount to a narrowly
scoped Google service account without shipping service-account JSON keys into
Pods. RBAC limits what the control plane and workload identities can do. The
environment model also uses namespace-scoped service accounts and default-deny
network policy to make a workload's access intentionally small.

This is a more complex setup than giving every Pod a broad cloud credential,
but it protects the cloud account if a user workload is compromised. The
backup integration is specifically gated: Rudder does not turn on GCS/CNPG
backup behavior until the identity binding and recovery proof are approved.

## 4. Building and running applications

### Docker and Docker Compose

Docker is the first runtime because it gives a small, understandable local
loop: build an image, start a container, health-check it, and route traffic to
it. `docker-compose.dev.yml` starts the local development dependencies:
PostgreSQL, registry, BuildKit, Traefik, control plane, and agent.

Docker Compose is also an import source. Rudder reads an imported Compose
graph and turns it into its service model rather than treating the file as an
unrestricted command script. This supports familiar application layouts such
as app + PostgreSQL + Redis while retaining Rudder's lifecycle controls.

The limitation is that Docker's host-local networking and volumes do not make
a robust production multi-host scheduler by themselves. Phase 2 added a
private agent/scheduler runtime; Phase 3 moved the production resource model
to Kubernetes.

### The aiohttp node agent and Docker SDK

The agent is a small `aiohttp` service using the Docker SDK. It owns the
actual containers on one node; the control plane owns desired state. Agents
register, heartbeat capacity and observed containers, create releases, check
health, collect logs, and remove discarded replicas.

This boundary avoids giving the central API an unrestricted Docker socket on
every host. It also lets the scheduler reason about node capacity and allows a
reconciler to detect stale heartbeats and recover stateless work. The trade-off
is a distributed-system failure mode: an agent can be unreachable while its
containers continue to exist. Generation fencing, deadlines, health checks,
and conservative handling of persistent volumes are used to avoid pretending
that such a state is safe.

### BuildKit and registries

BuildKit builds source into OCI container images. Locally it pushes to a
private development registry; Docker workers later pull the same immutable
image reference. The local dev stack deliberately shares BuildKit's network
namespace with the registry so `localhost:5000` means the same registry from
the build worker and host Docker daemon.

BuildKit is used because it has a focused build interface and efficient
container-image behavior. It should not be exposed as a general user command
executor. In the old GCP VM lab the rootful BuildKit exception was constrained
to a private VPC because the image did not support the required rootless user
namespace setup; this is not the production model.

### Cloud Build and Artifact Registry on GKE

GKE production does not depend on a Compose-local BuildKit daemon. The GCP
path sends approved source/build context through Cloud Build and publishes to
Artifact Registry. Deployments use immutable digest references, not mutable
tags. A digest lets an operator answer exactly what ran and roll back without
rebuilding.

Artifact Registry and Cloud Build cost money per stored image and build
minute. Digest retention needs an explicit policy: retaining every artifact
improves rollback/audit availability but increases storage cost; deleting
artifacts too aggressively invalidates permanent release URLs and rollbacks.

### Runtime choices: Docker, distributed Docker, Kind, and GKE

| Runtime | Intended use | What Rudder controls | Important boundary |
| --- | --- | --- | --- |
| Docker Compose | Local development/single host | Containers, local routes, local registry/builds | Not a production multi-host ingress system |
| Agent-backed Docker | Private Phase 2 lab | Scheduler, node agents, Docker containers | No public cross-host workload routing promised |
| Kind | Local Kubernetes acceptance | Namespaces, deployments, services, ingress, policies | Developer cluster; not managed production capacity |
| GKE Standard | GCP production reference | Namespaced workloads and app-level desired state | Terraform owns cluster/cloud foundation; Rudder attaches |

This distinction prevents a frequent operational mistake: pointing a local
runtime variable at a production cluster and assuming local registry, backup,
or credential behavior is safe in production.

## 5. Kubernetes platform components

### Kubernetes and `kubernetes-asyncio`

Kubernetes is the production workload API. The control plane uses the async
Kubernetes client rather than shelling out to `kubectl`. That makes rendered
resources testable, enables structured API errors, and keeps the desired-state
logic inside the same authorization and transaction model as other API work.

One Rudder environment maps to a dedicated namespace. Imported services map
roughly as follows:

- stateless applications/workers become Deployments;
- stateful dependencies become StatefulSets with PVCs;
- private components receive ClusterIP Services and CoreDNS names;
- only explicitly public apps receive an Ingress;
- candidate releases must become ready before stable traffic promotion.

This approach gives an operational unit for quotas, policy, secrets, cleanup,
and diagnostics. Namespace isolation is useful, but a complete commercial
multi-tenant platform still requires account, billing, rate-limit, audit, and
provider-isolation work beyond a namespace.

### Kind, Calico, ingress-nginx, and MinIO

Kind creates Kubernetes-in-Docker for local verification. The bootstrap script
installs Calico (so NetworkPolicy is enforced), ingress-nginx, and optionally
CloudNativePG. `make verify-kind` creates a disposable composed release and
checks routing, candidate failure behavior, cleanup, and isolation guardrails.

MinIO is an S3-compatible local object store used for local CloudNativePG
backup tests. It is deliberately **not** the GKE backup path and its local
access settings must not be copied into production.

These tools make the local test path closely resemble the resource model of
GKE. They do not reproduce a cloud provider's IAM, load balancer billing,
quota, control-plane availability, or real regional failure modes.

### ingress-nginx, cert-manager, ExternalDNS, and Cloud DNS

Ingress-nginx is the Kubernetes HTTP routing controller. cert-manager obtains
and renews certificates. On GCP, ExternalDNS manages DNS records only in the
delegated Rudder zone and only for explicitly Rudder-managed Ingresses; it
uses TXT ownership records so it does not accidentally claim unrelated DNS.

Cloud DNS and the Google load balancer are provider services at the edge,
because those cannot be replaced by a cluster-only process. This yields one
HTTPS edge while application routing remains declared in Kubernetes. Costs
come from load-balancer usage, DNS zones/queries, IP/network egress, and
certificate-validation operations rather than from cert-manager itself.

### CloudNativePG and persistent state

Catalog-managed PostgreSQL can be rendered as a CloudNativePG `Cluster`; its
data remains inside the Kubernetes model with persistent volumes and WAL/base
backup support. CloudNativePG was selected instead of a provider-managed
database to preserve the Kubernetes-only production workload model and keep
the same service-graph experience for app dependencies.

The price is operational responsibility: operator versions must be pinned,
backups must be tested by an actual restore drill, storage class and PVC
behavior matter, and data deletion needs a guarded process. Rudder's normal
control-plane identity intentionally does not get broad PVC-deletion powers.

## 6. GCP infrastructure and infrastructure-as-code

### Terraform

Terraform in `infra/gcp/terraform/` declares the GCP landing zone. It enables
the required APIs and manages the VPC/subnet ranges, private regional GKE
cluster, node pools, Artifact Registry, build/log/backup storage, DNS-related
identity, and least-privilege service accounts. A versioned, public-access-
prevented GCS backend is used for Terraform state.

Terraform owns the **foundation**, while Rudder owns environment
namespaces and workloads after attaching to the cluster. This prevents a
runtime deployment from accidentally recreating a cluster or changing global
cloud networking. It also makes `terraform plan` the reviewable record for
cloud changes.

### GKE Standard and node pools

The GCP reference chooses a private-node regional GKE Standard cluster. System,
platform, and optional workload pools separate provider/system duties,
Rudder's own control-plane/ingress duties, and environment workloads. GKE
node-pool autoscaling, auto-repair, and auto-upgrade can reduce some provider
operations, but Rudder does not provision or control the cluster autoscaler.
Separately, Rudder can reconcile workload-level HPAs for eligible Kubernetes
applications.

GKE has cost and quota consequences that are part of the design, not an
afterthought. Regional pools consume capacity across zones: for example, a
three-zone `e2-standard-2` pool consumes six vCPUs. The documented preflight
checks the project-wide `CPUS_ALL_REGIONS` quota rather than relying only on a
regional display. Machine hours, persistent disks, load balancers, object
storage, build minutes, registry storage, logs/metrics ingestion, and egress
are the main variable cost categories.

The project documented a real baseline constraint: the optional workload pool
is deliberately not enabled until regional CPU quota permits it. This is a
good example of an honest deployment gate: a green unit test does not create
cloud capacity.

### Helm and bootstrap scripts

Platform add-ons are installed through reviewed bootstrap scripts using pinned
Helm chart versions, not `latest`. The scripts install ingress-nginx,
cert-manager, External Secrets Operator, ExternalDNS, CloudNativePG, and the
control plane after Terraform establishes prerequisite identity and network
resources.

Helm provides repeatable packaging for third-party Kubernetes controllers;
Terraform is better suited to GCP resources. Mixing the two without a
boundary tends to create ownership confusion, so this repository documents
which layer owns which resource.

### Secret Manager and External Secrets Operator

GCP Secret Manager is intended to hold production secret material. External
Secrets Operator synchronizes approved secrets into Kubernetes namespaces.
This avoids committing credentials into manifests or passing service-account
JSON files through application configuration.

Secret synchronization needs least privilege and rotation procedures. It is
not a reason to make every namespace able to read every project secret. The
cost is typically modest compared with compute, but the security benefit comes
from access scoping and auditability rather than price.

## 7. Observability and operational data

### Logs

In the Docker-agent path, runtime logs are collected into bounded rotating
local files. In Kubernetes, Rudder reads Pod logs through the Kubernetes API.
The API and CLI expose a consistent service/deployment log contract, including
structured JSON Lines where requested. Build logs remain distinct from runtime
logs because an image build failure and an application crash are different
operator questions.

Bounded retention protects the control-plane host from unbounded disk growth,
but it means Rudder is not a long-term compliance log archive. Production
operators should set retention/export policy deliberately and account for
Cloud Logging/observability ingestion costs if forwarding is enabled.

### Metrics

Rudder records compact CPU-oriented runtime observations. Docker agents report
observed resource state; Kubernetes metrics are gathered from the resource
metrics API when available. Samples are compacted from frequent observations
to coarser time tiers so dashboard usefulness does not make the metadata
database grow forever.

Metrics are operational hints, not a substitute for a fully managed enterprise
observability stack. The repository also has a design path for per-environment
Prometheus/Grafana, normally private by default. Such components have material
CPU/memory/storage and scrape-cardinality costs, so they must be controlled as
an explicit operation rather than silently installed for every project.

## 8. AI assistance

### OpenAI Responses API

The Advisor service can use an `OPENAI_API_KEY` to call the OpenAI Responses
API. It is used for two bounded, advisory jobs:

- turning checked-out repository evidence into a proposed service graph;
- explaining deployment failure evidence in human-friendly language.

The AI response is not trusted configuration. Advisor proposals are ghost
nodes; each must be accepted through the normal resource APIs. Diagnoses and
the Ask Rudder dock are read-only and can return no diagnosis when the model
has no useful result. This protects against a model response silently creating
resources or changing production configuration.

AI use has both privacy and cost implications. Repository/build failure inputs
should be minimized and reviewed, secrets must be redacted before use, the API
key belongs only in server-side secret configuration, and model calls should
be bounded/cached where appropriate. If no API key is configured, the system
must degrade clearly rather than inventing an AI result.

## 9. Testing, validation, and developer tooling

### pytest, pytest-asyncio, and fakes

The backend and agent use pytest; pytest-asyncio exercises coroutine code.
Tests cover API authorization, database services, migration chains, runtime
rendering, deployment promotion/cleanup, logs, advisor behavior, and
reconciliation. Fakes/injected clients make scheduler and Kubernetes contract
tests deterministic without requiring a cloud cluster for every edit.

That is intentionally not the only verification level. `make verify-kind` is
the local Kubernetes integration/acceptance route, and GKE has preflight and
read-only verification scripts. A fake can prove that Rudder asked for a
NetworkPolicy; only an enforcing cluster can prove that traffic was denied.

### Vitest, Testing Library, TypeScript, and Ruff

Vitest tests the CLI and web UI. Testing Library focuses assertions on what an
operator can see and do rather than fragile internal component details.
`tsc --noEmit` checks TypeScript without producing output; builds prove that
the bundler/compiler can create deployable assets.

Ruff provides Python formatting/lint rules covering errors, imports, modern
syntax, common bug patterns, and async misuse. The normal validation set also
includes `git diff --check` to catch whitespace errors. These tools lower the
cost of reviewing a backend-heavy project, but they do not replace end-to-end
security review, cloud quotas, or production change management.

## 10. A request's end-to-end path

The following sequence ties the stack together:

1. An operator signs in through GitHub OAuth or a configured local/admin path,
   then uses the Next.js console or TypeScript CLI.
2. The client calls FastAPI. FastAPI authenticates the user, authorizes the
   relevant project/environment/service, validates input with Pydantic, and
   stores desired state in PostgreSQL.
3. For a source deployment, Rudder obtains permitted GitHub/App source,
   detects a build approach, and uses BuildKit locally or Cloud Build on GCP.
4. The output is an OCI image. Local paths use a private registry; GKE uses an
   Artifact Registry immutable digest.
5. The deployment service asks the selected runtime to apply a candidate:
   Docker through a node agent, or Kubernetes through the async API.
6. Health/readiness checks must succeed before stable routing changes. Failed
   candidates are cleaned up and the known-good service route remains where
   the runtime supports rolling promotion.
7. Instances, releases, logs, and metrics flow back into Rudder's operational
   records. The web console and CLI render that state through the same API.

This path is intentionally more structured than “SSH to a server and run
Docker.” It adds components and operational cost, but it gives repeatability,
traceability, a safer rollback story, and a way to evolve from local learning
infrastructure to a cloud provider foundation without changing the operator's
mental model.

## Related documents

- [Product overview](overview.md)
- [Architecture](architecture.md)
- [Features](features.md)
- [Configuration](configuration.md)
- [GKE operations](gke-operations.md)
- [Phase 4 controlled-beta evidence](evidence/phase-4-controlled-beta.md)
- [GCP and multi-cloud architecture](multi-cloud.md)
- [Documentation index](index.md)
- [Phase 4 GKE production runtime](phases/phase-4.md)
- [Phase 9 CLI parity](phases/phase-9.md)
