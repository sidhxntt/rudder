# Phase 3 — Kubernetes runtime

**Target:** 3–5 weeks

**Execution order:** Step 1 proves the adapter locally on Kind. Step 2 moves
the *same manifests and control-plane contract* to a GKE Standard cluster;
Kind is never presented as the production target.

**Demo:** import a Compose-backed GitHub repository; Rudder builds an immutable
image, deploys its public app and private dependencies into an isolated
Kubernetes namespace, then rolls back a failed revision without interrupting
the live URL.

This phase is the production-runtime track. It starts only after the Phase 2
control-plane invariants are verified: desired state, idempotent commands,
capacity accounting, health-gated rollout, and reconciliation. Kubernetes owns
container scheduling; Rudder continues to own product-level intent, deployment
history, domains, and the user-facing service graph.

## Scope

- Run Rudder's UI/API, metadata database, build queue, and image registry
  outside customer namespaces.
- Add a Kubernetes runtime adapter beside the existing local Docker adapter.
- Map Rudder services to Kubernetes resources:
  - stateless app, API, worker, scheduler, and realtime services → Deployments
  - stateful database, cache, broker, search, and storage services →
    StatefulSets plus PersistentVolumeClaims where Rudder manages them
  - private discovery → ClusterIP Services
  - public services → Gateway/Ingress routes with TLS
  - environment configuration → Secrets and ConfigMaps
- Give every Rudder project/environment an isolated namespace, service account,
  resource quota, limit range, and default-deny network policy.
- Build repository revisions in an isolated builder, push immutable image tags
  to a private registry, and deploy only those tags.
- Stream Kubernetes events and container logs into Rudder's existing deployment
  and service views.

## Step 1 — local Kind acceptance target

- Bootstrap a disposable Kind cluster, local registry bridge, and ingress-nginx
  with `make kind-up`. In development, the first confirmed UI import invokes
  this idempotently on the local host.
- Run the control plane with `RUDDER_RUNTIME=kubernetes` and a generated
  Docker-reachable kubeconfig via `make kind-control-plane`. The UI waits for
  `/healthz` to report `runtime: kubernetes` before it submits the release;
  later imports reuse the ready cluster without restarting the control plane.
- Verify the normal persisted import/deployment path creates one disposable
  project/environment namespace with `web + worker + PostgreSQL + Redis`.
- Verify a broken immutable candidate is deleted before route promotion and
  leaves the prior public URL serving.

This is the required first delivery for Phase 3. It verifies resource
translation, readiness gating, private discovery, ingress, instance recording,
and failure cleanup without treating a laptop cluster as production.

### Local operations controls verified on Kind

The local acceptance path also exercises the controls exposed in Rudder's
service detail panel. They reconcile from durable desired state to Kubernetes
objects; a requested value is never displayed as healthy until the release has
passed readiness.

- stateless replica count, CPU/RAM requests and limits, rolling updates, node
  selectors, preferred anti-affinity, topology spread, and a PodDisruptionBudget
  for HA workloads. Operators may set its safe `maxUnavailable` value; leaving
  it unset preserves Rudder's automatic `N - 1` availability policy;
- HPA min/max bounds, recurring CronJobs, and allowlisted one-off Jobs;
- immutable rollback by repointing the stable Ingress to a previous healthy
  workload — no source build, image rebuild, or restored-pod restart;
- catalog-managed PostgreSQL through CloudNativePG: private read endpoints,
  read-replica count, and only-upward storage expansion;
- Prometheus scrape annotations and Grafana integration intent. Rudder does
  not silently install a public observability stack for a tenant namespace.
- on-demand physical PostgreSQL backups through CloudNativePG only when a
  private S3-compatible endpoint, bucket, and credentials are configured.
  Credentials are written to a namespace Secret and never logs; each backup is
  one-shot and clears from desired state after the operator completes it.

PostgreSQL backup remains hidden until an engine-specific, object-storage
target is configured. Restore remains hidden even then: safe physical recovery
must create and validate a separate recovery Cluster before an explicit
application cutover, never overwrite a live primary in place. GKE production
must provide a bucket, workload identity, retention policy, encryption, and a
tested CloudNativePG recovery flow before restore is advertised.

## Step 2 — GKE Standard production target

Move the proven adapter to a regional GKE Standard cluster with private nodes,
Cloud DNS, a private Artifact Registry, workload identity, managed ingress,
and durable observability. The control plane stays outside tenant namespaces;
the runtime continues to create one constrained namespace per Rudder
environment.

## Production decisions required before GKE

- Select a cloud and managed Kubernetes service (for example DOKS, EKS, or
  GKE), region, private registry, DNS provider, and object storage.
- Define the split between Rudder-managed stateful services and managed cloud
  databases. The initial beta may offer managed-in-cluster PostgreSQL/Redis;
  production-critical workloads need backups, restores, and an explicit
  durability policy.
- Set tenant resource quotas, maximum replicas, permitted images, and build
  limits before accepting untrusted repositories.

## Verification

1. Two projects deploy into separate namespaces and cannot resolve or connect
   to one another's private services.
2. An imported `web + worker + PostgreSQL + Redis` topology gets one public
   URL for `web`; the other services remain private.
3. A new image revision becomes routable only after its readiness probe passes.
4. A deliberately failing revision is recorded as failed while the previous
   live URL continues to serve traffic.
5. The Kind acceptance script verifies workload controls, HPA, CronJob,
   one-off Job, PostgreSQL read replicas/storage expansion, HA disruption
   budget, immutable route rollback, and failed-candidate route preservation.
6. Deleting a project removes its namespace-owned workloads and routes while
   retaining Rudder deployment history according to the retention policy.
7. Resource-quota and network-policy tests prove one tenant cannot exhaust or
   access another tenant's resources.

## Relationship to Phase 4

This phase owns the private service network: Kubernetes Services, CoreDNS,
namespaces, and NetworkPolicies replaced the planned WireGuard mesh outright
([ADR 0004](../decisions/0004-kubernetes-networking-replaces-wireguard-mesh.md)).
Phase 4 does not re-solve networking. It takes this exact resource contract —
namespace, Deployment/StatefulSet, ClusterIP Service, PVC, Ingress, quota,
NetworkPolicy — off Kind and onto a private regional GKE cluster, and adds the
production concerns Kind cannot prove: Artifact Registry digests, Workload
Identity, managed HTTPS edge, durable state, and infrastructure-as-code.

If this phase's contract changes, Phase 4 changes with it. Keep it stable.

## Done when

- A managed Kubernetes cluster runs isolated Rudder environments end to end.
- GitHub import, build, deployment, logs, domains, readiness, and rollback all
  work through the Kubernetes adapter.
- Namespace/RBAC/quota/network-policy isolation is demonstrated with automated
  tests and a live acceptance test.
- Backup and restore behaviour for every supported stateful offering is
  documented and exercised.
