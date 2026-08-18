# Architecture: how Rudder turns intent into a release

This document explains the system before relying on phase-specific details.
For the project requirements and phase rationale, start with [overview.md](overview.md)
and the detailed [phase narratives](index.md#phases-how-the-platform-was-built).

## Design principles

1. **One control plane, many clients.** The web console and CLI are peers; both
   use the same REST resources and error contract.
2. **Desired state is durable.** Postgres records projects, environments,
   services, deployments, instances, domains, variables, operations, and
   ownership. A successful mutation describes requested intent, not merely a
   process that was started.
3. **The runtime is replaceable.** Docker agents were the early implementation;
   Kubernetes is the production runtime model. Runtime adapters preserve the
   control-plane vocabulary while rendering different infrastructure objects.
4. **Health precedes traffic.** A candidate must become ready before a stable
   alias moves. Failure records useful diagnostics and preserves the prior live
   route when one exists.
5. **Isolation is explicit.** Service visibility, domains, namespace naming,
   ownership checks, and NetworkPolicy are product semantics rather than UI
   conventions.

## Control plane

The Python 3.12/FastAPI control plane exposes resource-oriented HTTP routers.
It authenticates users, checks ownership at resource boundaries, validates
requests, encrypts sensitive variables, and persists intent in Postgres. It
does not make clients wait indefinitely for a long build or reconciler pass.

Two background responsibilities are central:

- The **deployment worker** claims queued deployment work and invokes the
  selected runtime/build path.
- The **reconciler** periodically compares recorded state with observed runtime
  state, marks stale heartbeats or missing instances, recovers eligible
  stateless replicas, consumes operations, and retries durable PR-ready
  notifications with backoff.

The separation makes failure handling tractable: an agent or pod can fail
without losing the database's intent, and retried work has an audit trail.

## Resource model

```text
User
  └─ Project
       └─ Environment
            ├─ Service (app, worker, database/cache, etc.)
            │    ├─ Deployment (immutable revision lifecycle)
            │    └─ Instance (observed runtime member)
            ├─ Variable (encrypted value / reference)
            ├─ Domain (stable service target or pinned deployment target)
            └─ Operation (requested action with observed result)
```

An environment is a declarative service graph. Cloning copies graph intent,
encrypted variables, and canvas placement, but intentionally does not copy
runtime history, build logs, domains, or volume data. This distinction stops a
new environment from accidentally inheriting live production traffic or data.

## Source-to-release flow

```text
GitHub installation / webhook
          │ signed event or approved interactive request
          ▼
import preview → confirmation → project/environment/service records
          │
          ▼
deployment queued → checkout pinned revision → detect or use Dockerfile
          │
          ▼
build immutable image → registry → runtime candidate
          │                         │
          │                         ├─ health/readiness
          │                         └─ logs + observed instances
          ▼
candidate healthy → publish/promote routes → mark LIVE → retire prior candidate
candidate failed  → persist error → clean candidate → keep existing stable route
```

For imported repositories, Rudder prefers a validated, normalized Compose
subset. If Compose is absent, it can detect supported application conventions
and generate a constrained plan. The operator reviews the import before it is
created; Advisor proposals are even more conservative and must be accepted
item-by-item.

## Runtime adapters

### Local Docker and multi-host agent path

**Implemented and historically verified.** The agent uses Docker APIs rather
than shelling out for container lifecycle. BuildKit builds images and a local
registry publishes them. Traefik reads dynamically generated routing config.
Nodes heartbeat capacity and observed containers; the scheduler selects a
healthy placement with sufficient capacity. Persistent Docker volumes are
node-local and are deliberately not auto-rescheduled across hosts.

This path is valuable for development and for explaining the desired/actual
state model. It is not the production network model for cross-host private
services.

### Kubernetes path: Kind locally, GKE as the implemented cloud target

**Implemented; local Kind verification and the
[GKE controlled-beta evidence](evidence/phase-4-controlled-beta.md) are
documented separately.** Each environment gets a namespace derived from
its immutable environment identifier. The adapter renders:

| Rudder concept | Kubernetes representation |
|---|---|
| stateless app / worker | Deployment |
| stateful dependency | StatefulSet + PVC |
| private service | ClusterIP Service |
| public service | Ingress after readiness |
| secret variables | Secret-mounted or injected configuration |
| service graph isolation | namespace + default-deny NetworkPolicy |
| environment identity | dedicated tokenless workload ServiceAccount |

Candidate and stable routing are managed as a small transaction-like sequence:
the candidate has to be ready; route writes are compensated on failure; a
release route gives the immutable deployment URL; and the stable route moves
only during promotion. Database state and route state are deliberately kept in
agreement as far as failures permit, with rollback/cleanup paths tested using
fakes.

## Network and security boundaries

### Authentication and ownership

GitHub OAuth links a user using GitHub's immutable numeric identity. GitHub App
access handles repository installation flows. Webhooks are separately
authenticated with an HMAC because GitHub does not hold a user session. CLI
browser handoff uses a short-lived authorization record; the browser never
receives the terminal's final bearer token.

Every resource router resolves ownership through the containing project or
environment. This is necessary even in a single-tenant product because it
prevents one authenticated identity from addressing another identity's object
by guessed ID.

### Variables and configuration

Sensitive variable values are encrypted at rest using configured Fernet keys
and redacted in service configuration responses. The graph supports references
between services within an environment, which are resolved in the deployment
path. Secrets are not written into public routing configuration or diagnostic
prompts.

### Kubernetes isolation

Rudder's Kubernetes design replaces a planned WireGuard mesh with native
Services, CoreDNS, namespaces, and NetworkPolicy. Workloads are private by
default; ingress is issued only for a declared public route. The GKE platform
also uses Workload Identity, namespace-scoped RBAC, and separate control-plane
and backup identities. See the [multi-cloud guide](multi-cloud.md) and
[Phase 3](phases/phase-3.md) for the networking decision.

This is isolation between Rudder environments, not a claim of sufficient
isolation for arbitrary hostile multi-tenant workloads.

## Observability and operations

Build logs, runtime logs, instances, and metrics are different data types:

- build logs explain image construction;
- runtime logs come from a local agent or Kubernetes pod log API;
- instances express observed lifecycle/health;
- CPU and memory samples are retained at compacted resolutions.

Operations are durable requested intents (restart, scale, rollback, backup,
observability configuration) rather than client-side `kubectl` actions. The
reconciler dispatches them and records their result, making refreshes and
retried requests safe to reason about.

Eligible Kubernetes application workloads also support autoscaling intent. The
runtime reconciles that intent as a `HorizontalPodAutoscaler`, leaving the HPA
as the sole replica controller. This does not add Docker autoscaling, provision
a GKE cluster/node autoscaler, or guarantee that the cluster has spare
capacity.

## GCP production topology

Terraform is the source of truth for the GCP foundation: VPC, private regional
GKE Standard cluster, Artifact Registry, object storage for backups/remote
state, service accounts, IAM, and DNS-related prerequisites. Rudder uses
**attach mode**: it owns environment namespaces and workloads but does not create,
upgrade, or delete the GKE cluster/node pools itself.

Portable in-cluster components include ingress-nginx, cert-manager,
CloudNativePG, and the Rudder control plane. Provider-specific components stay
at the edge: GCP load balancing, Artifact Registry, GCS, Cloud DNS, and
Workload Identity. The exact budget/capacity caveats belong in the Phase 4 and
[multi-cloud guide](multi-cloud.md) documents.

## Deliberate boundaries

Rudder does not presently promise teams/RBAC, billing, Docker or cluster/node
autoscaling, multi-region routing, an HA control plane, a serverless execution
model, or hardened SaaS multitenancy. Workload-level HPA reconciliation is
implemented only for eligible Kubernetes applications. Rudder also does not
currently provision AWS or Azure. Those boundaries are explicit rather than
hidden limitations. See
[conclusion.md](conclusion.md) and [multi-cloud.md](multi-cloud.md).
