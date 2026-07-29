# Kubernetes Operations Controls Design

## Goal

Give a Rudder user safe, functional controls for Kubernetes workloads and
managed data services. Every control must update desired state in the control
plane, reconcile to Kubernetes, and present the observed outcome in the UI.

## Scope and delivery shape

The feature is split into four independently deployable slices. The controls
share a service configuration model and an operations panel, but stateful data
operations remain distinct from stateless workload scaling.

| Slice | User-facing control | Kubernetes representation | Safety boundary |
| --- | --- | --- | --- |
| Workloads | replicas, CPU/RAM, public access, health checks, rollback | Deployment, Service, Ingress | readiness-gated revision promotion |
| Data | storage sizing, backup/restore, PostgreSQL read replicas, Redis persistence/replication | StatefulSet, PVC, CronJob | primary and replica roles cannot be swapped by a scale operation |
| Jobs | workers, scheduled jobs, one-off jobs | Deployment, CronJob, Job | explicit command, audit record, bounded retries |
| Operations | autoscaling, node placement, HA spread, rollout strategy, observability | HPA, affinity, PDB, canary/blue-green routing, metrics add-ons | capability validation before applying a release |

## Architecture

### Desired state

`Service` gains an `operations_config` JSON column. It is schema-validated at
the API boundary and is the durable intent for operations controls. It contains
only declarative values: workload role, replica bounds, CPU/memory request and
limit, exposure, scheduling rules, rollout strategy, data durability policy,
and job definitions. Secrets remain in Rudder variables; operation records
never contain plaintext credentials.

`Service` keeps the existing `replica_count`, `cpu_limit`, and
`memory_limit_mb` as compatibility fields. A migration/backfill normalizes
these values into `operations_config.workload`, while the public API accepts
both during the transition. The full replacement endpoint is idempotent;
partial updates only update declared keys.

### Runtime translation

The Kubernetes runtime receives a normalized `RuntimeServiceSpec` rather than
raw UI data. It maps:

- `web`, `api`, `worker`, `realtime`, and `scheduler` to Deployments;
- `postgres`, `mysql`, `mongodb`, `redis`, brokers, search engines, and
  storage to StatefulSets with PVCs;
- scheduled tasks to CronJobs and manual runs to Jobs;
- replica bounds plus CPU/memory signals to HPAs;
- HA options to PodDisruptionBudgets and topology spread constraints;
- public services to one ingress route only after candidate readiness.

The Compose importer produces this same normalized model. A user-supplied
Compose file remains authoritative; Rudder-generated Compose only fills gaps
for detected dependencies and templates.

### Deployment and rollback semantics

All app revision images are immutable. A rollback selects a prior immutable
revision and changes the public route to its already-healthy Kubernetes
workload; it must not rebuild source. Stateful data is never rolled back by
this action. Database restore is a separate, confirmation-gated operation
using a named backup and creates an audit record.

For blue/green releases, the candidate gets an isolated Deployment and only
the route selector changes after readiness. For canary releases, traffic
weights advance through configured steps and automatically return to the
current live revision when a readiness or metric gate fails. Kind supports the
same desired-state resources locally; GKE production swaps the ingress and
storage integrations without changing the API contract.

### Observed state

The reconciler reads Kubernetes workloads, pods, HPAs, Jobs, CronJobs, PVCs,
and backup Jobs. It persists lightweight operation status records and exposes
them through one service-operations endpoint. The UI never infers a service is
live solely from a requested setting: it renders `pending`, `progressing`,
`healthy`, `degraded`, `failed`, or `unknown` from observed Kubernetes state.

## API surface

All service operation APIs are scoped to `/services/{service_id}` and require
the service's environment ownership.

- `GET/PATCH /operations` — typed desired and observed operation state.
- `POST /operations/scale` — set a manual replica count for a stateless
  workload; rejected for database primaries.
- `POST /operations/autoscaling` — enable/update/disable an HPA.
- `POST /operations/rollout` — apply a requested canary or blue/green policy.
- `POST /operations/rollback` — select a prior immutable deployment; no build.
- `POST /operations/jobs/run` — run an approved one-off command as a Job.
- `POST /operations/schedules` and `DELETE /operations/schedules/{id}` —
  manage CronJobs.
- `POST /operations/data/backups` — create a backup Job; `POST .../restore`
  restores a selected backup after explicit acknowledgement.
- `POST /operations/data/read-replicas` — create or resize PostgreSQL/MySQL
  read replicas; primary writes are never redirected automatically.
- `POST /operations/data/storage` — request a PVC expansion; shrinking is
  rejected because Kubernetes cannot safely shrink bound volumes.
- `POST /operations/observability` — enable/disable Rudder-managed Prometheus
  and Grafana for the environment.

Each write returns an operation record with a stable id. Invalid combinations
(for example HPA and a fixed manual scale, read replicas on Redis, a public
database, or a storage decrease) return 422 before any Kubernetes call.

## UI

The detail panel adds an **Operations** tab with four sections:

1. **Run**: live health, pods, replicas, CPU/RAM, public URL, manual scale,
   autoscale bounds, and restore history.
2. **Release**: selected revision, readiness status, rollback, and rollout
   strategy. A rollback confirmation explicitly says “no source build”.
3. **Data**: only for managed stateful services—PVC size, backups, read
   replicas, replication health, and destructive-operation confirmations.
4. **Jobs & placement**: worker count, scheduled jobs, one-off command,
   restart policy, node selector, anti-affinity and HA spread.

The environment view adds a compact **Observability** card for Prometheus and
Grafana and a top-level health summary. Unsupported controls are hidden with a
concise explanation rather than shown as disabled generic form fields.

## Data support policy

Initial supported managed data roles:

- PostgreSQL: PVC expansion, backup/restore, read replicas, replication
  health, resource limits.
- MySQL/MariaDB: same capability shape as PostgreSQL.
- Redis: PVC persistence policy, memory limits, replicas/sentinel policy;
  not SQL read replicas.
- MongoDB: PVC expansion and replica-set membership when enabled in the
  selected template.

Message brokers, search engines, object storage, Prometheus, and Grafana are
managed through templates plus their resource/PVC/placement controls. Rudder
does not claim an unsafe generic backup/restore operation for a data engine
without an engine-specific implementation.

## Security and reliability

- Per-environment namespace quotas cap pods, requests, limits, and PVC count.
- Sensitive values live in Kubernetes Secrets, never operation JSON or logs.
- One-off jobs use allowlisted commands configured per service/template and
  have timeout, retry, and log retention limits.
- Backup and restore need confirmation and audit records; restore pauses
  writes for the affected service and records its source snapshot.
- Read replicas are private-only and get a separate read-only connection URL.
- Node placement accepts only configured labels/regions and validates
  capacity before rollout.
- Operations reconcile idempotently after control-plane restart.

## Verification

Automated tests cover API validation, desired-state persistence, runtime
manifest construction, observation mapping, and UI form behavior. Kind E2E
tests prove: app/worker manual scaling; HPA creation; a scheduled Job;
immutable rollback without image build; a private PostgreSQL replica; PVC
expansion; and a failed candidate preserving the public route. GKE acceptance
uses the same runtime contract and validates cloud storage/ingress behavior.
