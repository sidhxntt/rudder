# Phase 4 — GKE production networking and landing zone

**Target:** 3–5 weeks
**Owner:** Platform / infrastructure
**Status:** planned; do not deploy customer workloads until the acceptance
checklist passes.

> **Why this file is still named `PHASE-4-mesh.md`:** it preserves existing
> links. It is no longer a WireGuard implementation plan. Rudder's production
> path is GKE, where Kubernetes Services, CoreDNS, namespaces, and
> NetworkPolicies provide the private service network. WireGuard remains only a
> future non-Kubernetes/Docker-host alternative and is explicitly out of scope
> for this phase.

## One-sentence demo

A GitHub push builds an immutable image, deploys an isolated application,
worker, Postgres, and Redis stack to GKE; only the application has a public
HTTPS route, private services resolve by Kubernetes DNS, and a failed rollout
keeps the prior public revision serving traffic.

---

## 1. Handoff summary

### What already exists

- **Phase 1:** GitHub import, build, Compose-derived service graph, immutable
  deployment records, public-route handling, and rollback semantics.
- **Phase 2:** control plane, Rudder agents, heartbeats, scheduler, and
  reconciler were exercised across GCP VMs. Those VMs are a development and
  scheduler testbed, **not** the production GKE node pool.
- **Phase 3:** the Kubernetes runtime runs locally on Kind. It converts the
  reviewed service graph into an environment namespace, Deployments or
  StatefulSets, Services, PVCs, ingress, ResourceQuota, LimitRange, and
  NetworkPolicies. Local verification passed before this handoff.
- **Repository context:** the GCP project in use is `invytt-2483d`; the desired
  production platform is GKE, not the legacy WireGuard/Docker-host path.

### What Phase 4 delivers

Phase 4 turns that local runtime into a repeatable, secure GCP environment:

1. a regional, VPC-native **GKE Standard** cluster with private worker nodes;
2. private Artifact Registry, Google-managed identity, and least-privilege
   access;
3. public traffic through one managed ingress/gateway path only;
4. private, environment-scoped Kubernetes service networking;
5. external durable state where required (Cloud SQL, object storage, Secret
   Manager), rather than pretending local Kind volumes are production backups;
6. end-to-end proof that deployment, rollback, failure safety, and UI status
   agree with the actual GKE resources.

### Explicit non-goals

- No WireGuard peer/key/IP allocation work.
- No direct public endpoint for Postgres, Redis, workers, queues, or internal
  observability components.
- No “cluster per app” model. Rudder owns a shared GKE cluster; each Rudder
  environment owns an isolated namespace.
- No arbitrary cloud-provider abstraction in this phase. GCP is the first
  provider adapter; its interfaces must stay portable so EKS and AKS can follow.

---

## 2. Target architecture

```text
GitHub push / Rudder UI
          |
          v
Rudder control plane ----> Artifact Registry (immutable image digest)
          |
          v
GKE Standard regional cluster (private nodes, VPC-native)
  |
  +-- rudder-system namespace
  |     control-plane integration, ingress/gateway, observability agents
  |
  +-- rudder-<environment-id> namespace
        |
        +-- app Deployment -------- ClusterIP Service --- public Ingress/Gateway
        +-- worker Deployment ----- ClusterIP Service (private)
        +-- postgres StatefulSet -- ClusterIP Service (private)
        +-- redis StatefulSet ----- ClusterIP Service (private)
        +-- PVCs / Secrets / ConfigMaps / NetworkPolicies

Internet --> managed HTTPS load balancer --> public app Service
app/worker --> postgres.rudder-<environment-id>.svc.cluster.local
app/worker --> redis.rudder-<environment-id>.svc.cluster.local
```

### Networking contract

| Traffic | Required behaviour | Enforcement |
|---|---|---|
| Internet → application | HTTPS to explicitly public application services only | managed ingress/gateway, TLS certificate, allow-list of public services |
| Application → Postgres/Redis | Private DNS and private ClusterIP only | Kubernetes Service plus namespace NetworkPolicy |
| Worker → application/database/queue | Private, explicit only | namespace NetworkPolicy |
| Environment A → environment B | Denied by default | namespace isolation and default-deny NetworkPolicies |
| Pod → Google services | Only through its Kubernetes ServiceAccount/Workload Identity | Workload Identity and narrowly scoped Google IAM |
| Database/cache → Internet | Denied unless a documented backup or package mirror path requires it | egress NetworkPolicy and cloud firewall policy |

`<service>` is the supported in-namespace hostname. Cross-namespace use must
be intentional and use the fully qualified Kubernetes Service name. Rudder
does not allocate mesh IPs or write host-level DNS zones.

---

## 3. Required production decisions

These decisions must be recorded before provisioning. Do not silently choose a
different option during implementation.

| Decision | Recommended initial choice | Reason |
|---|---|---|
| Region | `asia-south1`, regional cluster | aligns with the current GCP footprint and tolerates one zonal failure |
| GKE mode | Standard, VPC-native, private nodes | Rudder needs predictable node pools, workloads, and operations controls |
| Cluster ownership | one shared Rudder production cluster | matches the namespace-per-environment runtime model |
| Control plane location | dedicated `rudder-system` namespace or separately managed service | separates platform authority from customer namespaces |
| Image registry | private Artifact Registry repository | immutable digest deployment and Google IAM integration |
| Public edge | GKE Gateway or managed Ingress, selected once and used consistently | one auditable path for TLS, domains, and routing |
| DNS and certificates | Cloud DNS + Google-managed certificates, or an explicitly documented alternative | public hostnames must have an ownership and renewal model |
| Secrets | Secret Manager + Workload Identity; synchronize only the values a pod needs | prevents broad project credentials in Pods |
| Primary relational database | Cloud SQL for real production customer data | provides backups, encryption, HA, and recovery workflows not present in local PVCs |
| Object storage | GCS bucket with retention and lifecycle rules | deployment artifacts, logs/export, and backup staging |

If cost or availability requires a smaller first acceptance cluster, it may use
one customer node pool temporarily. That exception must not weaken the network,
identity, backup, or public-route model.

---

## 4. Delivery sequence

### Step 1 — Establish the GCP foundation

1. Enable the required GCP APIs: GKE, Artifact Registry, IAM, Compute, Cloud
   DNS, Certificate Manager/selected edge service, Secret Manager, Logging,
   Monitoring, and Cloud SQL if used in the first acceptance run.
2. Create a dedicated VPC/subnet design for the cluster and configure secondary
   ranges for Pods and Services. Do not reuse an unmanaged Docker subnet.
3. Create the regional private GKE Standard cluster and separate node pools:
   system, build/platform, and customer workloads. Apply autoscaling bounds and
   resource limits from the start.
4. Create private Artifact Registry repositories and allow only the build
   identity to push. Runtime workloads pull immutable digests only.
5. Define Terraform or equivalent reviewed infrastructure-as-code as the source
   of truth. Manual console changes are emergency-only and must be backfilled
   into code.

**Exit criteria:** a clean GCP project can create the same cluster and
prerequisite services from reviewed infrastructure code.

### Step 2 — Establish identity and control-plane access

1. Create a dedicated Google service account for Rudder's control-plane
   deployment adapter and bind it to a Kubernetes ServiceAccount through
   Workload Identity.
2. Grant Kubernetes RBAC only for the resources Rudder owns: namespaces with
   the `rudder.*` labels, Deployments, StatefulSets, Services, Ingress/Gateway
   resources, Secrets, ConfigMaps, PVCs, Jobs, and status reads.
3. Use separate service identities for build/image publishing, public edge,
   backup, and application runtime. Avoid a project-owner credential in a Pod.
4. Configure Secret Manager access at the secret or environment boundary; do
   not pass long-lived GCP keys through GitHub, build logs, or Rudder variables.

**Exit criteria:** the control plane can reconcile one labelled environment,
but cannot modify unrelated namespaces or cloud resources.

### Step 3 — Carry the Kubernetes runtime to GKE

1. Keep the Phase 3 resource contract unchanged wherever possible:
   - environment → namespace;
   - application/worker → Deployment;
   - database/cache → StatefulSet and ClusterIP Service;
   - persistent state → PVC backed by the selected GKE storage class;
   - public application only → Ingress/Gateway route.
2. Make the runtime target selectable (`kind` for local development, `gke` for
   production) behind a provider/runtime configuration boundary. The UI must
   show the selected target and cluster/namespace, not pretend Kind is GKE.
3. Replace local registry assumptions with Artifact Registry image digests.
   A deployment record must retain the resolved digest and manifest revision.
4. Use readiness and liveness probes. Promote a route only after the new app
   revision is ready; a failing candidate never replaces the live route.
5. Preserve immutable deployment records. **Restore** re-points the active
   route and desired revision to a prior digest; it must not rebuild from the
   current Git branch.

**Exit criteria:** a known Phase 3 sample deploys from Artifact Registry to GKE
using the same Rudder API/UI workflow.

### Step 4 — Enforce private networking and public edge policy

1. Apply a namespace default-deny NetworkPolicy before creating customer
   workloads.
2. Add explicit policy for DNS, required private dependencies, required
   egress, and the selected ingress/gateway controller.
3. Create ClusterIP Services for Postgres, Redis, workers, queues, and internal
   monitoring. Rudder must reject a request to make these service kinds public.
4. Permit an Ingress/Gateway only for a service marked `public=true`; attach a
   managed certificate and a verified DNS name.
5. Keep database and cache ports off cloud load balancers, public node ports,
   and public firewall rules. Administrative access uses a documented,
   authenticated private path.
6. Enforce ResourceQuota and LimitRange for every Rudder environment; require
   requests and limits for app and worker workloads.

**Exit criteria:** private services work through DNS from allowed Pods and are
unreachable from the public Internet or another environment namespace.

### Step 5 — Durable state, observability, and recovery

1. Treat in-cluster Postgres/Redis as acceptance-test state unless a dedicated
   database operation model is approved. Production customer state should use
   managed services or an explicitly documented operator and backup design.
2. Configure automated database backups, PITR/retention where offered, storage
   encryption, restore drills, and secret rotation.
3. Send control-plane audit logs, GKE events, application logs, metrics, and
   deployment state to the selected observability stack. Prometheus/Grafana can
   be interpreted by Rudder later; Phase 4 needs dependable raw signals first.
4. Define alerts for failed rollouts, no-ready-replica, ingress errors,
   exhausted quota, image-pull failure, certificate expiry, and failed backup.

**Exit criteria:** an operator can identify which image, namespace, Pod, and
cloud identity served a deployment and can recover a tested data sample.

---

## 5. Provider-neutral boundary for future AWS and Azure

GCP is the first implementation, not the permanent product assumption. Keep
the Rudder core provider-neutral by exposing these capabilities instead of GCP
SDK calls throughout the control plane:

```text
CloudProvider
  ensure_cluster_target()
  publish_image(digest)
  resolve_runtime_credentials()
  ensure_public_route(host, service, tls_policy)
  provision_managed_database(spec)          # later operations phase
  provision_object_storage(spec)            # later operations phase
  observe_runtime(target, namespace)
```

The Kubernetes workload adapter remains shared. The GCP adapter maps these
capabilities to GKE, Artifact Registry, IAM/Workload Identity, Cloud DNS, and
the chosen Google edge/database/storage services. Future adapters map the same
contract to EKS/ECR/IAM/Route 53 and AKS/ACR/Managed Identity/Azure DNS.

Do not create AWS or Azure resources in Phase 4. Instead, write provider
contracts and acceptance tests so a later implementation can satisfy the same
behaviour without changing deployment records, UI semantics, or the service
graph.

---

## 6. Failure safety and runbooks

| Failure | Required system behaviour | Operator response |
|---|---|---|
| Build fails | candidate remains failed; last live revision stays routed | inspect immutable build log; fix/retry without route change |
| New app Pod never becomes ready | no promotion; deployment marked failed/rolled back | inspect Pod events, probes, image, quota, and NetworkPolicy |
| Database/cache StatefulSet not ready | app route is not promoted if dependency readiness is required | inspect PVC binding, image pulls, readiness, credentials, storage class |
| GKE node loss | Kubernetes reschedules eligible Pods; Rudder UI reflects actual replica state | verify Pod relocation and public endpoint continuity |
| Control-plane outage | existing GKE workloads continue; new deploys/changes queue or fail clearly | restore control-plane service; reconcile desired versus actual state |
| Bad deployment | restore a prior immutable deployment record; never rebuild it | record incident, validate old digest and route health |
| Public route/certificate failure | private workloads remain isolated; no accidental direct exposure | inspect Gateway/Ingress, DNS ownership, certificate status, load balancer logs |

### Required runbooks

- GKE cluster access and break-glass procedure
- failed deployment / readiness diagnosis
- immutable deployment restore
- namespace and environment cleanup
- database backup and restore drill
- lost node / node-pool incident
- compromised GitHub token, cloud identity, or application secret rotation
- public DNS/certificate incident

---

## 7. End-to-end verification

Run this against a disposable GKE acceptance environment before customer use.
Record commands, screenshots, and the resulting deployment IDs in the Phase 4
checkpoint.

### Functional path

1. Import a private GitHub repository containing `app`, `worker`, `postgres`,
   and `redis` through the Rudder UI.
2. Confirm Rudder builds an immutable image and publishes it to Artifact
   Registry.
3. Confirm it creates one labelled environment namespace and the expected
   Kubernetes resources.
4. Confirm only the application receives a public HTTPS route.
5. From the application Pod, resolve and connect to Postgres and Redis using
   Kubernetes service DNS.
6. Confirm the worker processes a test job without gaining a public route.

### Isolation and identity path

1. From outside the cluster, verify Postgres/Redis ports are not reachable.
2. From a Pod in a second Rudder environment, verify the first environment's
   private services are denied.
3. Verify the runtime service account can access only its intended Google
   resources and that no static cloud credential is present in Pod environment
   variables, build logs, or Rudder API responses.
4. Verify quotas reject an intentionally over-sized workload with a clear
   Rudder error.

### Reliability path

1. Deploy a deliberately broken revision; verify the old public URL continues
   to serve and the candidate is shown as failed.
2. Restore a previous immutable deployment; verify the control plane uses the
   stored digest/manifest and does not rebuild from Git.
3. Kill a customer node or drain a node pool; verify Kubernetes reschedules
   replicas and the public endpoint remains available within the defined SLO.
4. Push one committed change through GitHub; verify exactly one deduplicated
   deployment starts and its Git SHA is recorded.
5. Run a database backup/restore drill against a disposable data set.

### UI truthfulness checks

- The UI shows GKE target, namespace, deployment revision/digest, workload
  readiness, current public hostname, and private-service status.
- It distinguishes build failure, scheduling failure, readiness failure, and
  route promotion failure.
- It does not show a service as `live` merely because a Pod exists; readiness
  and public route health determine public live state.
- It exposes a restore action only for a completed immutable deployment.

---

## 8. Done when

- [ ] GKE Standard cluster and dependencies are reproducible from reviewed
      infrastructure-as-code.
- [ ] Rudder deploys immutable Artifact Registry images into labelled GKE
      environment namespaces.
- [ ] Workload Identity, least-privilege RBAC, and secret access are verified.
- [ ] Default-deny isolation is active; only explicitly allowed private traffic
      works.
- [ ] Only explicitly public application services receive managed HTTPS routes.
- [ ] Databases, caches, workers, queues, and internal observability services
      have no public endpoint.
- [ ] A broken candidate leaves the prior live URL serving traffic.
- [ ] Immutable restore reuses a recorded digest and does not rebuild.
- [ ] GKE node loss reschedules workloads and the UI reflects the transition.
- [ ] Backup/restore, secret rotation, DNS/certificate, and incident runbooks
      are written and exercised.
- [ ] The Phase 4 checkpoint documents the exact cluster configuration,
      deployment IDs, verification evidence, known limitations, and teardown
      procedure.

---

## References and follow-on work

- [Phase 3 — Kubernetes runtime](PHASE-3-kubernetes-runtime.md) is the local
  Kind contract Phase 4 carries to GKE.
- [Phase 5 — environments](PHASE-5-environments.md) owns cloning and
  promotion semantics after GKE environment isolation exists.
- [Phase 6 — operations](PHASE-6-operations.md) expands managed database,
  volume, logs, metrics, and restore products after this foundation is proven.
- Update `docs/phases/README.md`, `docs/PRD.md`, and later phase references in
  the Phase 4 implementation plan: they currently describe this file as the
  legacy WireGuard alternative and must be aligned before Phase 4 is marked
  complete.
