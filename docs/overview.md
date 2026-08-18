# Rudder: a beginner's guide

Rudder is a self-hosted platform for taking a source-code repository and
turning it into a running application with a visible release history, a public
URL when appropriate, private service-to-service networking, and operational
controls. Its experience is inspired by Railway and Vercel, but its purpose is
different: the operator owns the control plane and the infrastructure rather
than handing both to a hosted PaaS.

> **Reality check.** Rudder is currently a learning build and is deliberately
> **single-tenant**. A project is isolated from other projects in the current
> system, but it is not a hardened SaaS boundary for mutually untrusted
> customers. The multi-cloud material in [multi-cloud.md](multi-cloud.md)
> describes a future provider-portability design, not an AWS or Azure release.

## The problem it addresses

Deploying a small application is deceptively repetitive. A team normally has
to choose a build image, publish it, create runtime configuration, attach a
database, keep the database private, route web traffic, observe failures, and
repeat the process on every source revision. Those concerns are valuable but
they should not require a new bespoke script for each repository.

Rudder makes the deployment intent explicit:

1. An operator selects a GitHub repository and revision.
2. Rudder imports a reviewed Compose graph, or detects a simple application and
   proposes a generated one.
3. The control plane records the desired project, environment, services,
   variables, domains, and deployment.
4. A runtime adapter turns that intent into Docker resources locally or
   Kubernetes resources in Kind/GKE.
5. Rudder waits for health, exposes only declared public services, retains the
   prior working release during a failed rollout, and projects state, logs, and
   metrics back to the operator.

This is a **long-running-container platform**, not serverless computing. An API,
worker, frontend, database, and cache can share one environment while following
the same basic lifecycle.

## What an operator can do

### Import and manually deploy

The web workspace can connect to GitHub, inspect an installation/repository/
branch, preview the proposed service graph, and require confirmation before it
creates a project. A deployment can then be requested deliberately. This is
the Railway-style part of the product: visual services, variables, domains,
deployment history, logs, metrics, and operations in one workspace.

### Deploy automatically from source events

GitHub webhooks are authenticated with an HMAC and route source events into the
same deployment machinery. Pull-request events can create capped, ephemeral
preview environments and queue their deployment. The implementation includes
idempotency-oriented handling and a retrying PR-ready notification outbox.
Actual GitHub credentials, public webhook DNS, and an installed GitHub App are
operator configuration; without them Rudder stays usable for the deterministic
local flows.

### Use the terminal instead of the browser

The supported `rudder` CLI is Node/TypeScript. In a terminal it offers a
GitHub-authenticated launcher; with flags it is suitable for automation and
JSON output. It talks only to the same authenticated control-plane API as the
web interface. It does not call Docker, Kubernetes, Terraform, or cloud APIs
directly. That constraint prevents a second, drifting implementation of the
platform.

### Get advice without surrendering control

Rudder Advisor scans a checked-out repository and proposes services and
relationships as reviewable ghost nodes. The operator accepts individual
proposals through ordinary resource APIs. Build-failure diagnosis and the
**Ask Rudder** assistant are read-only. When an OpenAI key is absent, the
platform's normal deployment features still work; model-backed wording is an
optional enhancement, not a deployment dependency.

## Why it is built this way

### Desired state and actual state are separate

The database is the authoritative record of what the operator asked for. A
Docker agent or Kubernetes runtime reports what is actually running. A
reconciler closes the gap: it detects lost instances, consumes pending
operations, performs bounded recovery work, and avoids allowing a node to make
its own scheduling policy. This separation is important because containers and
pods can die, networks can partition, and a successful API response is not
proof that a workload is healthy.

### One service graph, not separate frontend and backend products

Rudder treats a static frontend as a build artifact packaged in a small nginx
container; an SSR frontend is an ordinary app container. A worker and a web app
are both stateless workloads; a database and cache are stateful dependencies.
This avoids making one deployment system for backends and a different one for
frontends, while still giving static sites appropriate cache and SPA-fallback
behaviour.

### Private-by-default dependencies

Only an explicitly public app gets a public route. Databases, caches, and
workers receive private discovery endpoints. In Kubernetes, one environment
maps to one namespace with default-deny network policy, ClusterIP services,
DNS-based discovery, secrets, and workload identity. In the earlier local
Docker path, Traefik reaches containers on the private Docker network and
containers do not publish host ports.

### A stable service URL and an immutable release URL solve different jobs

A service domain tracks the current live deployment (Railway-style). A
deployment-pinned domain points at one immutable release (Vercel-style). The
first lets an operator roll forward or back without changing the main address;
the second makes a review link durable and makes it possible to identify the
exact artifact a reviewer saw.

## The architecture at a glance

```text
web canvas / CLI / automation
             │ same authenticated REST API
             ▼
 FastAPI control plane ─── Postgres (desired state, history, operations)
             │
    deployment worker + reconciler
             │ runtime adapter
     ┌───────┴────────┐
     ▼                ▼
 local Docker      Kind / GKE Kubernetes
 agent path        namespace per environment
```

The detailed component and request-flow view is in
[architecture.md](architecture.md). The technology choices are in
[tech-stack.md](tech-stack.md), and the phase-by-phase construction narrative
continues in the [phase sequence](index.md#phases-how-the-platform-was-built).

## What is implemented, verified, and planned?

This documentation intentionally uses three labels:

- **Implemented** means code/configuration exists in this repository.
- **Verified** means there is recorded test or acceptance evidence. It does not
  mean every external production integration has been exercised at every point
  in time.
- **Planned / mapped** means the design is documented but not an implemented
  provider or product guarantee.

Examples: the local Docker flow and the Kubernetes resource contract have
implementation and tests; GKE has a Terraform landing zone and a
[controlled-beta evidence record](evidence/phase-4-controlled-beta.md); AWS and
Azure are provider mappings only. Consult each phase's verification section
for the exact strength of evidence.

## Why the work is split into phases

Rudder could not safely start with a GKE cluster, an AI assistant, and a large
web canvas. Each would hide whether the fundamental operation—turning source
into a healthy, reachable workload—was correct. The phases therefore reduce
the number of unknowns at each step and insist on a showable result before
adding a new class of risk.

| Phase group | Question it answers | Why it comes at this point |
|---|---|---|
| 0: baseline | What are the product contract, non-goals, local setup, and architecture decisions? | Prevents later code from silently choosing incompatible models. |
| 1: one host | Can one source revision build, become healthy, receive a URL, and preserve the old release on failure? | Proves the smallest end-to-end release loop. |
| 2: multiple hosts | Who schedules work, how is capacity observed, and what happens when a node disappears? | Adds distributed-systems failure modes only after a working single-host lifecycle exists. |
| 3: Kubernetes locally | Can the same graph become namespace-isolated Deployments, StatefulSets, Services, and Ingresses? | Uses Kind to test a portable resource contract without cloud account cost. |
| 4: GCP landing zone | Can that contract run with private networking, immutable registry images, identity, TLS, backups, and Terraform? | Adds cloud economics and operational ownership after the Kubernetes contract is already known. |
| 5–7: delivery usability | Can people create isolated environments, operate services, inspect history, and deploy frontends/review URLs? | Makes the primitive useful for real daily delivery. |
| 8: assistance | Can analysis improve setup and diagnosis without gaining mutation authority? | Places AI behind proven APIs and an explicit human approval boundary. |
| 9: CLI parity | Can all operator workflows happen without a browser and without creating a second backend? | Finishes the interface surface after the resources it exposes already exist. |

This ordering also controls cost. Docker and Kind expose correctness issues on a
developer machine; GKE is introduced only for requirements that need a real
provider (private regional nodes, Artifact Registry, DNS/TLS integration,
Workload Identity, object storage, and managed cluster operations). The
production-oriented infrastructure is intentionally attach mode: Terraform
creates the expensive/shared GCP foundation once, while Rudder creates and
deletes environment-scoped namespace resources. That division prevents a
routine application deployment from unexpectedly changing cluster lifecycle or
cloud capacity.

## How to read the documentation

1. Start with this page and [architecture.md](architecture.md).
2. Read [features.md](features.md) for the operator-facing product surface.
3. Read [tech-stack.md](tech-stack.md) and [multi-cloud.md](multi-cloud.md) for
   implementation and portability context.
4. Follow the [phase sequence](index.md#phases-how-the-platform-was-built) from Phase 0 to Phase 9 for the
   chronological engineering story.
5. Use the [technology guide](tech-stack.md),
   [configuration guide](configuration.md), and
   [GKE operations guide](gke-operations.md) when configuring a real environment.

For the complete navigation map, use [index.md](index.md). The final
perspective and current boundaries are collected in [conclusion.md](conclusion.md).
