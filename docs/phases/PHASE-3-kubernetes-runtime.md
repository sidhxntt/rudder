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
  with `make kind-up`.
- Run the control plane with `RUDDER_RUNTIME=kubernetes` and a generated
  Docker-reachable kubeconfig via `make kind-control-plane`.
- Verify the normal persisted import/deployment path creates one disposable
  project/environment namespace with `web + worker + PostgreSQL + Redis`.
- Verify a broken immutable candidate is deleted before route promotion and
  leaves the prior public URL serving.

This is the required first delivery for Phase 3. It verifies resource
translation, readiness gating, private discovery, ingress, instance recording,
and failure cleanup without treating a laptop cluster as production.

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
5. Deleting a project removes its namespace-owned workloads and routes while
   retaining Rudder deployment history according to the retention policy.
6. Resource-quota and network-policy tests prove one tenant cannot exhaust or
   access another tenant's resources.

## Relationship to Phase 4

For the Kubernetes production track, this phase replaces the Docker-host
networking portion of Phase 4: Kubernetes Services, namespaces, and NetworkPolicies
provide private service discovery and isolation instead of a WireGuard mesh.
Phase 4 remains the alternative path for the non-Kubernetes, multi-Docker-host
runtime.

## Done when

- A managed Kubernetes cluster runs isolated Rudder environments end to end.
- GitHub import, build, deployment, logs, domains, readiness, and rollback all
  work through the Kubernetes adapter.
- Namespace/RBAC/quota/network-policy isolation is demonstrated with automated
  tests and a live acceptance test.
- Backup and restore behaviour for every supported stateful offering is
  documented and exercised.
