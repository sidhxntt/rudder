# Engineering challenges: how Rudder was built phase by phase

Rudder looks like a visual deployment tool, but its difficult work happens
between a Git commit and a healthy, routable, recoverable release. A control
plane has to keep its record of intent consistent while builders, runtimes,
networks, GitHub, and cloud services fail independently.

This page consolidates the main engineering problem from every build phase.
It explains the operator-facing failure first, then the underlying cause, the
implemented treatment, the evidence, and the boundary that still remains. The
detailed [Phase 0–9 retrospectives](phases/phase-0.md) remain authoritative.

## A few useful words first

| Term | Plain-English meaning |
| --- | --- |
| Control plane | The API and database that remember what should exist and coordinate the work needed to make it exist. |
| Desired state | Rudder's durable record of the services, releases, routes, variables, and environments an operator asked for. |
| Observed state | What a Docker agent or Kubernetes currently reports as running. |
| Reconciliation | Comparing desired and observed state, then safely repairing a difference. |
| Immutable release | A built artifact tied to one source revision; rollback reuses it instead of rebuilding changing source. |
| Candidate | A new release that must prove healthy before it can receive live traffic. |
| Generation fencing | A version counter that prevents an old observation from overriding newer intent. |
| Installation token | A short-lived GitHub App credential scoped to repositories approved for one App installation. |
| Idempotent | Safe to process again without creating duplicate state or repeating a destructive effect. |
| Workload Identity | GKE's way to give a Pod narrowly scoped Google Cloud permissions without placing a service-account key in it. |

## Phase 0: avoiding accidental architecture

### The problem

A deployment demo can be built quickly by running Docker commands, routing by
service name, and storing little history. That shortcut becomes the product's
architecture: adding multiple hosts, rollback, domains, or Kubernetes later
then requires a rewrite.

### Why it was difficult

There was no runtime evidence yet. The team had to choose concepts that were
specific enough to guide Phase 1 without pretending future multi-cloud or
multi-tenant behavior was already known.

### How Rudder handles it

Rudder was defined as a control plane. PostgreSQL owns desired state and
deployment history; runtime adapters apply it. Domains were modeled separately
from services, canvas coordinates were kept as UI metadata rather than
deployment truth, and an agent boundary existed before there was a second host.
Security and evidence rules were also recorded before cloud resources existed.

### How it was verified

Phase 0 is a decision record, not runtime proof. Its test was whether a Phase 1
implementation could be derived from the documented model, interfaces,
constraints, and local setup without oral history.

### Remaining boundary

No deployment, availability, cloud security, or tenant isolation was proved.
See [Phase 0](phases/phase-0.md).

## Phase 1: promoting a new release without breaking the healthy one

### The problem

Two pushes can race, a candidate can pass one health check and die immediately,
a browser can disconnect while a build continues, and cleanup can leave a
container or route behind. Any of these can make the UI disagree with reality
or replace a working release with a broken one.

### Why it was difficult

Build, runtime, health, routing, logs, and deletion are separate operations.
They cannot be committed as one database transaction, and failures can happen
between any two steps.

### How Rudder handles it

The API records an immutable queued deployment before asynchronous work begins.
Build logs persist independently of SSE clients. A PostgreSQL advisory lock
serializes deployments for one service, superseding stale non-terminal work.
The candidate is health-checked and its liveness is checked again immediately
before Traefik promotion. The old instance drains only after the route changes.
Teardown reconciles runtime and routes before deleting catalog state.

### How it was verified

Recorded local acceptance deployed Node and Python services, preserved the old
URL after a broken Dockerfile, recovered a stopped container, processed a real
signed webhook, and reduced two near-simultaneous deploys to one live and one
superseded result.

### Remaining boundary

This proved one Docker host, not cross-host failover, production TLS, durable
off-host backup, or hostile-workload isolation. See [Phase 1](phases/phase-1.md).

## Phase 2: reconciling delayed information across Docker hosts

### The problem

Once several workers exist, Rudder must place replicas without overcommitting
capacity and recover from an unreachable node without starting a second copy of
a stateful workload against empty or stale data.

### Why it was difficult

Heartbeats are observations, not current truth. A delayed heartbeat can report
an instance missing after a newer command created it. An idempotent reconciler
can still oscillate forever if it repeatedly trusts stale reports. Concurrent
schedulers can also both see the same final CPU or memory slot.

### How Rudder handles it

Placement locks the selected node row and records allocation plus instance in
one transaction. Intent and heartbeat generations fence delayed observations.
After the heartbeat threshold, Rudder marks the node unreachable and sends it
no commands. Stateless work may be replaced; volume-backed work stays
explicitly unavailable until an operator restores or fences it. Returning
nodes only clean up Rudder-labelled orphans.

### How it was verified

The two-worker GCP lab stopped one agent beyond the stale threshold, observed a
single stateless replacement on the surviving node, and accepted the returning
worker. Concurrency, stale-report, idle-reconciler, and stateful-policy tests
exercise the underlying contracts.

### Remaining boundary

The lab proved scheduler behavior, not uninterrupted public traffic: the Docker
workers did not have a shared production ingress or private mesh. Kubernetes
became the production networking path. See [Phase 2](phases/phase-2.md).

## Phase 3: translating product intent into safe Kubernetes resources

### The problem

A Compose graph can contain a public app, private workers, databases, caches,
volumes, and scheduled work. Naively converting everything to Deployments and
Ingresses exposes dependencies, misrepresents readiness, and risks deleting
state during failed rollout cleanup.

### Why it was difficult

Kubernetes accepting an object does not mean the product is healthy. Apply,
readiness, route promotion, instance accounting, compensation, and deletion
cross API boundaries. Kind can validate translation while still differing from
GKE identity, DNS, certificates, backups, and load balancing.

### How Rudder handles it

Each environment maps to a namespace with quota, limits, default-deny network
policy, controlled ingress, and scoped service identity. Service roles select
Deployment or stateful primitives; private dependencies receive ClusterIP DNS
only. Release-qualified candidates must become ready before stable routing
moves. Compensation removes failed stateless candidates and restores routes,
while ordinary release cleanup is structurally unable to delete stateful PVCs.

### How it was verified

Runtime, deployment, namespace, logs, metrics, and verifier tests cover
translation, readiness, compensation, isolation configuration, and teardown.
Kind is the disposable contract harness; GKE supplies the cloud-specific proof.

### Remaining boundary

Automated manifests are not a substitute for a fresh live cross-namespace
denial and quota-exhaustion drill on a healthy cluster. See
[Phase 3](phases/phase-3.md).

## Phase 4: reaching GKE without hiding identity, recovery, or cost limits

### The problem

A production-reference path needs private builds, immutable image identity,
public HTTPS, DNS, backups, restore, alerts, and safe node maintenance. A ready
Pod alone cannot prove any of those. Cloud quota can also make the architecturally
preferred node topology impossible or unnecessarily expensive.

### Why it was difficult

Cloud Build, Artifact Registry, GKE, ingress-nginx, Cloud DNS, ExternalDNS,
cert-manager, CloudNativePG, GCS, IAM, and Secret Manager each have independent
identity and failure modes. A misconfigured certificate or DNS record can fail
after workload readiness; a successful backup does not prove restore; adding a
regional node pool multiplies requested capacity across zones.

### How Rudder handles it

Terraform owns the GCP foundation and Rudder uses attach mode: it manages
environment namespaces and workloads, not cluster lifecycle. Cloud Build
publishes immutable Artifact Registry digests. Workload Identity and scoped
RBAC avoid static cloud keys. Bootstrap fails closed on identity, database,
migration, image, hostname, DNS, and secret prerequisites. Promotion remains
health-gated, and CloudNativePG backup, restore, point-in-time recovery, and
normal node-drain behavior have explicit drills.

Capacity was treated as a product boundary rather than bypassed. The recorded
project quota was 12 of 12 vCPUs used. A three-zone `e2-standard-2` pool needs
six additional vCPUs, so the optional dedicated workloads pool stayed disabled
and the controlled beta used reviewed shared regional capacity.

### How it was verified

The dated [controlled-beta evidence](evidence/phase-4-controlled-beta.md)
records a real GitHub App deployment, Artifact Registry digest, application,
Redis and PostgreSQL readiness, public HTTPS `200`, rollback without rebuild,
broken-candidate route preservation, backup/restore/PITR, network denial, node
drain, metrics, secrets, DNS, and certificate checks.

### Remaining boundary

This is one regional GKE cluster, not six clusters. Six is the vCPU requirement
of one proposed regional pool. The shared-pool beta is not hardened hosted
multi-tenancy or unlimited production capacity. See [Phase 4](phases/phase-4.md)
and [GKE operations](gke-operations.md).

## Phase 5: making pull-request environments disposable without making them unsafe

### The problem

A PR preview needs an isolated copy of a service graph and branch-specific
releases, then complete cleanup on close. Repeated or reordered GitHub events
must not duplicate environments. Copying production data into a disposable
preview would be both dangerous and expensive.

### Why it was difficult

Graph cloning includes services, variables, volumes, domains, and Compose owner
relationships. Partial copies create unusable catalogs. GitHub retries webhook
deliveries, and namespace deletion can remain stuck after the API accepted it.
Every preview may consume compute, PVC, DNS, certificate, and backup capacity.

### How Rudder handles it

Clone creation is one transaction with reference rewrites and rollback on any
failure. Volume declarations are copied, never production contents or node
affinity. The PR number is the idempotency key for open, reopen, synchronize,
and close. Deletion waits with a monotonic timeout and leaves retriable catalog
state if runtime cleanup is incomplete. A configured per-project PR limit caps
capacity. Ready/queued GitHub comments use a durable retrying outbox.

### How it was verified

Tests cover atomic copy and rollback, graph cycles and reference rewrites,
Compose mappings, repeated PR events, cleanup, and namespace deletion errors.

### Remaining boundary

A real post-change acceptance still needs to open a PR, inspect its namespace,
PVC and domain, then close it and prove every resource is gone. Preview data
must come from migrations or fixtures, not cloned production storage. See
[Phase 5](phases/phase-5.md).

## Phase 6: operating stateful services and telemetry without lying about safety

### The problem

A scheduler can “recover” a database onto a node that has no data. Crash loops
can fill disks with logs, metrics can grow forever, and a rollback can point at
an artifact or workload that no longer exists. Ordinary deletion can erase a
PVC an operator expected to retain.

### Why it was difficult

Availability and data integrity can conflict. Logs and metrics are themselves
workloads with storage and failure costs. Rollback only remains trustworthy if
release identity and routing survive garbage collection and later promotions.

### How Rudder handles it

Docker volumes hard-pin a service to one node and prohibit silent relocation.
Database templates generate credentials once through encrypted variables.
Runtime logs are bounded and record truncation; metrics use fixed sampling,
compaction, and expiry tiers. Kubernetes metrics are best-effort and never gate
deployment. Rollback re-promotes a known healthy immutable release without
building again. Kubernetes RBAC keeps PVC deletion behind an explicit
break-glass path.

### How it was verified

Automated checks cover placement restrictions, credential stability, log
backpressure and retention, metric compaction, Kubernetes observation, and
route rollback.

### Remaining boundary

Live operational drills remain stronger evidence: preserve a database row
through redeploy, refuse relocation after node loss, survive excessive logs,
and restore an old release with zero build activity. See
[Phase 6](phases/phase-6.md).

## Phase 7: treating frontend output as an immutable release

### The problem

Static SPAs, exported frameworks, and server-rendered Next.js applications have
different output directories, fallback rules, cache behavior, and public build
variables. A generic container guess can serve stale entry HTML, break client
routing, leak variables, or make a historical release URL mutable.

### Why it was difficult

Assets benefit from immutable caching while `index.html` must remain fresh.
Framework inference must never override a repository-owned Dockerfile. Every
permanent release URL creates real DNS, ingress, and certificate lifecycle work.

### How Rudder handles it

An explicit Dockerfile always wins. Otherwise deterministic detection selects
Vite, CRA, static Next, Astro, or Next SSR behavior. Static builds use a
multi-stage image and non-root nginx, with SPA fallback only where valid.
Public build variables are prefix-allowlisted and changing them creates a new
release. Each healthy deployment receives an immutable release-qualified
domain; the normal service domain remains the movable live alias.

### How it was verified

Focused tests cover detection, templates, output selection, build-variable
filtering, permanent domains, promotion, and dashboard history.

### Remaining boundary

The strongest live proof remains two static releases: both permanent URLs must
answer, the live alias must roll back without rebuilding, and fallback must
appear only for actual SPAs. DNS propagation and certificate issuance remain
external dependencies with cost. See [Phase 7](phases/phase-7.md).

## Phase 8: using AI without giving probabilistic output deployment authority

### The problem

Repository contents and logs can help explain a service, but they are untrusted,
potentially prompt-injecting, and sometimes enormous. A plausible model answer
must not silently create infrastructure or replace raw operational evidence.

### Why it was difficult

Useful context competes with latency, token cost, privacy, and injection risk.
Combining proposal generation and mutation in one component would make it hard
to prove what an AI-assisted scan is allowed to change.

### How Rudder handles it

The repository advisor is deterministic and reads only bounded recognized
files. It emits stable proposals and has no database session or Rudder API
client. Operators accept individual proposals through normal resource APIs.
Optional diagnosis sends a bounded, clipped log tail and scoped configuration
through an injectable model boundary, labels the result, and leaves raw logs
visible. Ask Rudder is read-only and has no deploy, rollback, variable-write, or
acceptance tool. Missing model credentials disable only model-backed help.

### How it was verified

Tests require repeat scans to remain stable, exercise framework/dependency
recognition, prove single-item acceptance does not apply other proposals, and
keep model boundaries injectable and optional.

### Remaining boundary

Rudder does not claim perfect inference, autonomous remediation, or security
scanning. Model output is advice, not incident truth. See
[Phase 8](phases/phase-8.md).

## Phase 9: giving the CLI parity without creating a second control plane

### The problem

A CLI can become a dangerous bypass if it talks directly to Docker, Kubernetes,
Terraform, or the database. Human prompts also conflict with automation, giant
JSON responses obscure useful status, browser login handoffs can hang, and
terminal errors can accidentally disclose tokens or write-only variables.

### Why it was difficult

One interface must support guided TTY use and deterministic CI contracts.
Launching a browser does not produce a reliable completion signal. Web and CLI
must still observe exactly the same authorization, reconciliation, and history.

### How Rudder handles it

The TypeScript CLI uses one typed client for the same authenticated API as the
web console. Non-interactive flags, JSON/JSONL output, stderr progress, stable
exit codes, explicit destructive confirmation, and ambiguity errors form the
automation contract. Status is split into compact, detailed, and safely
redacted AI-summary views. Login uses a short-lived, opaque, single-use handoff:
the CLI opens GitHub OAuth in a browser and polls for a normal Rudder bearer
token without exposing that token to the page. Polling and browser settlement
are bounded. Tokens and variables are masked from output.

### How it was verified

CLI tests cover commands, cancellation, output contracts, status formatting,
URL validation, graph ownership, authentication, and secret-safe behavior.

### Remaining boundary

Full browser-auth and live web-to-CLI parity remain environment-dependent
acceptance exercises. Interactive credentials currently use a sensitive local
config file; an OS credential store is a future hardening step. See
[Phase 9](phases/phase-9.md).

## GitHub has four separate jobs in Rudder

Calling all of these “the GitHub integration” hides important security
boundaries:

| GitHub capability | Role in Rudder | What it is not |
| --- | --- | --- |
| GitHub OAuth | Authenticates a human for web sign-in and the CLI browser handoff, resolving users by immutable GitHub identity. | It is not the credential used to clone deployment source. |
| GitHub App | Grants installation-scoped access to approved repositories. Short-lived installation tokens list repositories and branches, read source, check out the exact revision, and post PR environment comments. | It is not a user session and does not grant access to every repository owned by the user. |
| Signed webhooks | HMAC-verified push and pull-request events start deployment or preview lifecycle work, with idempotency and retry-safe handling. | Receiving an unsigned HTTP request is never enough to queue a release. |
| GitHub Packages | Hosts the scoped `@sidhxntt/rudder` npm package used to install the CLI. | It is not Rudder's application-image registry; local builds use the development registry and the GCP reference uses Artifact Registry. |

See [Configuration](configuration.md) for credentials and callbacks, the
[technology stack](tech-stack.md) for security rationale, and the
[CLI installation guide](../cli/node/README.md) for GitHub Packages setup.

## Lessons that survived every phase

1. Persist intent before starting work that can outlive a request.
2. Never promote traffic merely because an API accepted a workload object.
3. Fence stale observations; idempotency alone does not solve delayed state.
4. Prefer data integrity over automatic recovery for stateful workloads.
5. Make rollback reuse a verified immutable release instead of rebuilding.
6. Keep human identity, repository authority, event authenticity, and package
   distribution in separate credential boundaries.
7. Treat capacity and cloud cost as architecture constraints, not footnotes.
8. Label tests, live evidence, and planned architecture separately.

## Where to look in the implementation

- [`control-plane/rudder_cp/services/deploy.py`](../control-plane/rudder_cp/services/deploy.py) — deployment sequencing, locking, promotion, and compensation.
- [`control-plane/rudder_cp/services/reconciler.py`](../control-plane/rudder_cp/services/reconciler.py) — desired/observed-state repair and node-loss policy.
- [`control-plane/rudder_cp/runtime/kubernetes.py`](../control-plane/rudder_cp/runtime/kubernetes.py) — Kubernetes translation, readiness, routing, logs, and metrics.
- [`control-plane/rudder_cp/services/github_oauth.py`](../control-plane/rudder_cp/services/github_oauth.py) — human OAuth authorization-code flow.
- [`control-plane/rudder_cp/services/github_app.py`](../control-plane/rudder_cp/services/github_app.py) — installation-scoped repository access and PR comments.
- [`control-plane/rudder_cp/routers/webhooks.py`](../control-plane/rudder_cp/routers/webhooks.py) — signed push and pull-request delivery.
- [`control-plane/rudder_cp/services/advisor.py`](../control-plane/rudder_cp/services/advisor.py) — bounded deterministic repository analysis.
- [`cli/node/`](../cli/node/) — terminal client, browser handoff, and GitHub Packages installation.
- [`infra/gcp/terraform/`](../infra/gcp/terraform/) — GCP foundation, identity, registry, cluster, DNS, and backup infrastructure.
