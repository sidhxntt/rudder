# Phase 4 — GKE production runtime and landing zone

**Target:** 3–5 weeks
**Owner:** Platform / infrastructure
**Status:** **complete for controlled beta** as of 2026-08-15. The core GKE
delivery path, GCS backup/full-restore/PITR, public TLS,
deployed-environment isolation, failed-candidate continuity, node-drain
recovery, and operational acceptance drills are verified. Customer workloads
intentionally share the tainted platform pool; a dedicated workloads pool is a
post-Phase capacity expansion, not a Phase 4 exit criterion. This is not a
general customer-production service commitment.

> Rudder's production path is GKE, where Kubernetes Services, CoreDNS,
> namespaces, and NetworkPolicies provide the private service network.
> WireGuard is **cancelled** as a Rudder deliverable, not deferred — see
> [ADR 0004](../decisions/0004-kubernetes-networking-replaces-wireguard-mesh.md).
> Reviving it for non-Kubernetes Docker hosts would need a new phase and its own
> ADR.

### Live re-verification — 2026-08-12

- The `rudder-gke` cluster is `RUNNING`, all six nodes are `Ready`, and the
  platform operators, control plane, and backup-identity broker are running.
- The latest recorded Phase 4 Cloud Build succeeded and published immutable
  digest `sha256:7c888b7f57633f594044501afad9147225c5e46de2487df0fc1ececd47f14e6c`.
- The project-wide `CPUS_ALL_REGIONS` quota remains exhausted at 12/12, so the
  dedicated workloads pool remains blocked and customer workloads must continue
  using the shared platform-pool contract.
- All active platform and deployed-workload Pods were Ready after recovery.
  The managed PostgreSQL cluster reported `Ready`, `ContinuousArchiving=True`,
  and `LastBackupSucceeded=True`.
- GKE Calico applies service egress after DNS translation. CNPG backup Pods
  therefore receive DNS-port-only egress, constrained by the CNPG cluster
  selector; metadata proxy traffic and Google API HTTPS remain separately
  scoped. This form was verified by a disposable restore Pod.
- The same default-deny policy permits only labelled `cloudnative-pg` Pods in
  `cnpg-system` to reach a database Pod's TCP/8000 status endpoint. This is
  required for CNPG health extraction and does not expose PostgreSQL itself.
- Successful Kubernetes promotions remove their superseded stateless release
  resources after route promotion. Deployment records and stateful workloads
  remain for rollback and data safety, preventing abandoned app revisions from
  exhausting the shared platform-pool CPU reservation.

## One-sentence demo

A GitHub push builds an immutable image, deploys an isolated application,
worker, Postgres, and Redis stack to GKE; only the application has a public
HTTPS route, private services resolve by Kubernetes DNS, and a failed rollout
keeps the prior public revision serving traffic.

### Implementation snapshot — 2026-07-30

The repository now has the first GKE-ready runtime boundary:

- `RUDDER_KUBERNETES_TARGET=gke` uses in-cluster Workload Identity rather than
  an operator kubeconfig, accepts only immutable Artifact Registry digests, and
  records a Kubernetes accounting projection instead of depending on a legacy
  Phase 2 agent node.
- The Kubernetes translation renders public GKE routes with stable TLS Secrets
  and a required cert-manager `ClusterIssuer`; Kind remains an explicitly local
  HTTP development target.
- `infra/gcp/scripts/bootstrap-platform.sh` installs the platform operators,
  a Workload-Identity-backed Cloud DNS ACME issuer, a zone-scoped ExternalDNS
  controller, and the control-plane HTTPS ingress. ExternalDNS receives a
  direct identity for only `external-dns/external-dns`, observes only
  Rudder-labelled Ingresses, and uses TXT ownership within the delegated zone.
  The bootstrap requires explicit image/chart/hostname inputs and makes no
  unreviewed version selection.
- Terraform describes the imported regional GKE baseline and the deferred
  workload pool.
- The control-plane container installs the checked-in `uv.lock` runtime graph
  without development dependencies. A fresh migration-chain test proves the
  image runs `alembic upgrade head` before serving `/healthz`; production runs
  that same image against CloudNativePG/PostgreSQL through the migration Job.
- The historical static S3 backup settings are now rejected for the `gke`
  target. They remain available only for an isolated Kind + MinIO development
  target. Terraform no longer binds the backup identity to
  `rudder-system`: CNPG database Pods live in per-environment namespaces, so
  that binding would be non-functional as well as misleading.

### Verified GKE delivery slice — 2026-07-31

The first end-to-end GKE release path has now been exercised against the live
`rudder-gke` cluster in `asia-south1`:

1. A push to an installed GitHub App repository triggered exactly one Rudder
   deployment for commit `106b06e83c903352050942790f1b8569d9de62f7`.
2. The control plane archived that exact revision, submitted it to regional
   Cloud Build using the dedicated Rudder build service account and source/log
   buckets, and published an immutable Artifact Registry digest.
3. Rudder applied the release into the environment namespace
   `rudder-b7c60f6bfc8a`. The application Deployment, Redis StatefulSet and
   Postgres workload reached Ready; the application, Postgres and Redis were
   observed running across the shared GKE platform pool.
4. ExternalDNS published the application hostname under
   `rudder.invytt.com`; cert-manager issued its certificate; the public HTTPS
   route returned HTTP 200 and the expected sample application response.
5. A restore was exercised from a prior live immutable deployment and then
   restored to the newest immutable deployment. Deployment history count did
   not increase during either operation, proving restore re-points a stored
   image rather than rebuilding from the current Git branch.

The exact deployment IDs, image digests, commands, completed evidence, and
remaining gates are recorded in [the Phase 4 checkpoint](checkpoints/PHASE-4-COMPLETION.md).

**Backup/restore production gate — passed 2026-08-12:** the GCS bucket,
dedicated backup Google service account, and separately deployed private
identity broker are live. The broker runs as its own Workload Identity, has only
a custom role for reading and setting IAM policy, and accepts requests only from
the labelled control-plane Pods through a `ClusterIP` Service plus
`NetworkPolicy`. It binds only the generated CNPG ServiceAccount in the
requested `rudder-*` environment namespace to the dedicated backup GSA; the
control plane itself has no IAM policy-write permission. The backup identity has
bucket-scoped `roles/storage.objectAdmin`, which is required by Barman to manage
backup metadata and WAL objects. A physical backup completed, continuous WAL
archiving was healthy, and a separate non-public CNPG cluster restored the GCS
backup and passed a read-only catalog comparison before being deleted.

Google IAM does not support scoping `setIamPolicy` directly to one service
account, so the broker's three-permission custom role is necessarily granted at
the GCP project level. The application-level broker validation, private network
boundary, dedicated ServiceAccount, and exact member check are the compensating
controls; this residual scope must remain documented and audited. Do **not** set
`RUDDER_KUBERNETES_BACKUP_GCS_IDENTITY_READY=true` or expose GKE backup controls
until one real generated CNPG ServiceAccount binding and a disposable backup /
restore drill have passed. That evidence now exists; retain the restriction. A
broad node identity, all-cluster principal, static S3/HMAC key, or JSON
service-account key is explicitly rejected.

The cloud gate is deliberate: GKE admits the regional workloads pool against
the project-wide Compute **`CPUS_ALL_REGIONS`** quota, not the regional
`CPUS` display. At the last verification, that authoritative quota was
**12 used / 12 limit**; the regional e2-standard-2 pool needs six more vCPUs.
For the initial production topology, customer Pods therefore share the tainted
`platform` pool with Rudder's control plane. The runtime enforces
`rudder.pool=platform` plus the matching `NoSchedule` toleration for every
Deployment, StatefulSet, CloudNativePG cluster, CronJob, and Job. Set
`enable_workloads_pool=true` only after aggregate quota reaches at least 18,
Terraform creates the dedicated pool, and a reviewed deployment switches
`RUDDER_KUBERNETES_WORKLOAD_POOL` to `workloads`.
The Terraform deployer also needs authority to write the three Workload Identity
service-account policy bindings. Neither blocker should be bypassed by
shrinking security controls or manually changing cluster state.

Run `infra/gcp/scripts/preflight-gke.sh` with `RUDDER_GCP_PROJECT`,
`RUDDER_GCP_REGION`, and `RUDDER_GKE_CLUSTER` before enabling the workloads
pool. The read-only preflight confirms the live cluster is running, verifies
the expected Workload Identity pool, proves Terraform's Application Default
Credential is valid, and checks both total and available project-wide
`CPUS_ALL_REGIONS` quota.
It fails closed with the exact credential or quota shortfall and never modifies
cloud resources. An invalid ADC requires `gcloud auth application-default
login`; an ordinary `gcloud auth login` alone is not sufficient for Terraform.

**Latest live check — 2026-07-31:** `rudder-gke` remains `RUNNING` with healthy
regional `system` and `platform` pools, and Workload Identity remains
`invytt-2483d.svc.id.goog`. Application Default Credentials are valid. The
authoritative **project-wide** quota remains **`CPUS_ALL_REGIONS = 12 used / 12
limit`**, even though the unrelated `asia-south1` **regional** `CPUS` display
shows `32`. GKE rejects a three-zone e2-standard-2 workloads pool against the
former quota, so `enable_workloads_pool` remains false until `CPUS_ALL_REGIONS`
is granted at least 18. Request 24 using the Google Cloud Console's Quotas &
System Limits page, filtering for the exact project-wide `CPUS_ALL_REGIONS`
metric rather than regional `CPUS`: Google's Quota Preferences API does not
expose this legacy GCE quota. The Cloud Audit entry is the source of truth for
this distinction; do not infer GKE capacity from regional `CPUS`.

Terraform has now created the `rudder-secret-sync` identity, its narrowly
scoped Workload Identity and Secret Manager reader bindings, and the empty
`rudder-control-plane-runtime` Secret Manager container. The first immutable
control-plane artifact is published at
`asia-south1-docker.pkg.dev/invytt-2483d/rudder/control-plane@sha256:bfd3e0f830ad80524891d5afdebcafcdc046e25b074062be04441f53028665c2`.
There is deliberately no runtime secret version yet, and public DNS delegation
is still absent (`dig NS rudder.invytt.com` returns no Cloud DNS nameservers),
so the shared platform bootstrap must not run yet.

**Verified baseline repair — 2026-07-30:** Terraform removed an erroneous
`NoSchedule` taint from the imported system pool in-place (no nodes or pools
were destroyed). All six nodes are Ready, the three system nodes now have no
taint, and both CoreDNS replicas recovered to `Running`. The platform pool
retains its `rudder.pool=platform:NoSchedule` taint; the Rudder control-plane
and ingress manifests now carry the matching toleration. `terraform plan` is
clean after the repair. This validates cluster health only — it does **not**
mean the platform bootstrap or customer workload acceptance path is complete.

### Platform bootstrap contract — handoff checklist

`infra/gcp/scripts/bootstrap-platform.sh` is the supported installer for shared
GKE platform components. It deliberately fails closed and does **not** create
customer environments. Before running it, an operator must complete all of the
following:

1. Refresh Terraform's local Application Default Credentials with
   `gcloud auth application-default login`. Normal `gcloud auth login` is not
   enough for Terraform's Google provider.
2. Apply the reviewed Terraform plan so the Secret Manager container,
   `rudder-secret-sync` identity, exact Secret Manager reader binding, runtime
   Workload Identity binding, Artifact Registry, Cloud DNS zone, and GKE
   identities exist. Terraform never writes a secret version.
3. Add an operator-managed JSON version to Secret Manager secret
   `rudder-control-plane-runtime`. It must contain at least
   `RUDDER_SECRET_KEYS`, `RUDDER_JWT_SECRET`, `RUDDER_ADMIN_EMAIL`, and
   `RUDDER_ADMIN_PASSWORD`; include GitHub OAuth/App fields only when those
   integrations are enabled. Never put that JSON, an OAuth client secret, a
   GitHub private key, password, JWT, or Fernet key in Git, Terraform variables,
   logs, or shell history.
4. Push the control-plane image to Artifact Registry and record its immutable
   `@sha256:` digest. Tags such as `latest` are intentionally rejected.
5. Delegate the Cloud DNS zone at the registrar and verify
   `dig NS rudder.invytt.com` returns the Cloud DNS nameservers. Choose a
   `RUDDER_KUBERNETES_PUBLIC_DOMAIN` equal to that suffix or a subdomain of it,
   and a control-plane hostname beneath that domain.
6. Pin the ingress-nginx, cert-manager, External Secrets, ExternalDNS, and
   CloudNativePG Helm versions in the operator command. Never use an unpinned
   chart version in production.

The bootstrap order is security-significant:

```text
External Secrets identity and SecretStore
  -> synced runtime Secret
  -> CloudNativePG three-instance control-plane database
  -> CNPG generated application URI Secret
  -> one migration Job (`alembic upgrade head`)
  -> control-plane Deployment, ClusterIssuer, and HTTPS Ingress
```

The API uses only the CNPG-generated database URI; it does not retain a
hard-coded `localhost` database fallback in GKE. A failed secret sync, database
readiness check, migration, or image/hostname preflight stops the bootstrap
before the public API Deployment is created. The controlled-beta acceptance
gate is complete. Repeat periodic isolation/private-endpoint audits as service
types expand, and treat the dedicated workloads-pool capacity as a post-Phase
production-expansion requirement. DNS delegation, immutable images,
broker-backed full restore and PITR, failed-candidate continuity, node-drain
recovery, and the scoped secret-rotation/DNS/certificate drills are verified.

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
5. durable in-cluster state under the CloudNativePG operator, with WAL archiving
   and backups to object storage and a drilled restore — rather than pretending
   local Kind volumes are production backups;
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
  +-- system node pool (untainted)
  |     GKE-managed add-ons such as CoreDNS and metrics components
  |
  +-- platform node pool (rudder.pool=platform:NoSchedule)
  |     Rudder control plane and public ingress, each with an explicit toleration
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
| Internet → application | HTTPS to explicitly public application services only | ingress-nginx, cert-manager certificate, allow-list of public services |
| Application → Postgres/Redis | Private DNS and private ClusterIP only | Kubernetes Service plus namespace NetworkPolicy |
| Worker → application/database/queue | Private, explicit only | namespace NetworkPolicy |
| Environment A → environment B | Denied by default | namespace isolation and default-deny NetworkPolicies |
| Pod → Google services | Only through its Kubernetes ServiceAccount/Workload Identity | Workload Identity and narrowly scoped Google IAM |
| Database/cache → Internet | Denied unless a documented backup or package mirror path requires it | egress NetworkPolicy and cloud firewall policy |

`<service>` is the supported in-namespace hostname. Cross-namespace use must
be intentional and use the fully qualified Kubernetes Service name. Rudder
does not allocate mesh IPs or write host-level DNS zones.

### Node-pool scheduling contract

The regional cluster has three roles. The **system** pool is deliberately
untainted so GKE-managed add-ons that cannot know about Rudder's taints (for
example CoreDNS) always have a schedulable home. The **platform** pool remains
tainted `rudder.pool=platform:NoSchedule`; Rudder's control plane and
ingress-nginx explicitly select and tolerate it. The optional **workloads**
pool is untainted and reserved for customer namespaces through labels,
admission rules, and namespace policy rather than a global taint. This avoids
starving cluster DNS while retaining a clear control-plane boundary.

---

## 3. Required production decisions

**Decided and recorded 2026-07-29** ([ADR 0005](../decisions/0005-phase-4-kubernetes-only-attach-mode.md)).
Do not silently choose differently during implementation.

The governing decision is **Kubernetes-only, even in production**: every runtime
component Rudder operates lives in the cluster. Managed GCP services are used only
where nothing can run in-cluster by nature — the L4 load balancer that fronts
ingress, object storage, the image registry, and the identity that reaches those.

| Decision | Choice | Reason |
|---|---|---|
| Region | `asia-south1`, regional cluster | already the configured project default; tolerates one zonal failure |
| GKE mode | Standard, VPC-native, private nodes | predictable node pools and operations controls |
| Cluster ownership | **attach** — Terraform provisions one shared cluster, Rudder consumes a kubeconfig | Rudder owns namespaces and workloads, not cluster lifecycle. Smallest blast radius and the cheapest path to EKS/AKS |
| Control plane location | dedicated `rudder-system` namespace | separates platform authority from customer namespaces |
| Image registry | private Artifact Registry repository | immutable digest deployment, Google IAM integration |
| Public edge | **ingress-nginx**, one controller, one auditable path | portable across GKE/EKS/AKS unchanged, unlike GKE Gateway or a cloud-specific Ingress class |
| Certificates | **cert-manager** + Let's Encrypt | runs in-cluster, portable; Google-managed certificates would bind the edge to GCP |
| DNS | Cloud DNS zone for `rudder.invytt.com`, delegated from GoDaddy | see step 1; the zone provider is an acknowledged per-cloud seam |
| Secrets | Secret Manager + Workload Identity; sync only the values a Pod needs | prevents broad project credentials in Pods |
| Primary relational database | **in-cluster Postgres via the CloudNativePG operator** — not Cloud SQL | K8s-only mandate. CNPG supplies replication, failover election, PITR through WAL archiving, and scheduled backups. A hand-rolled StatefulSet does not and must not hold customer data |
| Object storage | GCS bucket with retention and lifecycle rules, reached through CloudNativePG's native GKE Workload Identity flow | WAL archive, backups, deployment artifacts. The provider contract stays portable; authentication is provider-specific |

If cost or availability requires a smaller first acceptance cluster, it may use
one customer node pool temporarily. That exception must not weaken the network,
identity, backup, or public-route model.

### What K8s-only costs us, stated plainly

Dropping Cloud SQL saves roughly $50–150/month and removes a GCP dependency, and
transfers to Rudder: Postgres version upgrades, WAL archive correctness, failover
verification, replication-lag monitoring, connection pooling, and restore drills.
The asymmetric risk is not downtime — it is Rudder's own reconciler deleting a
StatefulSet's PVC and destroying customer data unrecoverably, which a managed
service's independent lifecycle would have prevented. Two controls are therefore
**mandatory**, not optional hardening:

1. Postgres runs under CloudNativePG with WAL archiving to object storage and a
   restore drill that has actually been executed against a disposable dataset.
2. Rudder's control plane must be structurally unable to delete a stateful PVC:
   RBAC denies PVC deletion, and stateful volumes carry a retain policy plus
   deletion protection. Environment teardown deletes stateful volumes only through
   an explicit, separately authorised operator path.

---

## 4. Delivery sequence

### Step 1 — Establish the GCP foundation

Attach mode means Terraform provisions this foundation once and Rudder never
touches it at runtime. Rudder receives only a kubeconfig.

Environment audited across 2026-07-29–30 on `invytt-2483d`: billing is enabled,
the regional `rudder-gke` baseline exists, and the system/platform pools consume
the current **12-vCPU project-wide `CPUS_ALL_REGIONS` quota**. A Cloud DNS zone
delegation, Artifact Registry repository verification, and the Workload Identity
policy bindings remain acceptance prerequisites. Customer releases initially
share the tainted `platform` pool; a separate workload pool is a later capacity
upgrade, not a blocker for this constrained beta topology.
The Phase 2
`rudder-vpc` custom-mode VPC is historical and must not be silently reused for
the GKE pod/service ranges.

1. ~~Enable the required GCP APIs~~ — **done 2026-07-29.** All ten are enabled:
   container, artifactregistry, iam, compute, dns, certificatemanager,
   secretmanager, logging, monitoring, sqladmin. (`sqladmin` is enabled but
   unused; K8s-only means no Cloud SQL instance.)
2. Create a GCS bucket for Terraform remote state with versioning enabled, and
   configure the backend before the first `apply`. Local state for a shared
   cluster is how two operators silently destroy each other's work.
3. Decide `rudder-vpc` explicitly: **reuse it or replace it, in writing.** It was
   built for the Phase 2 Docker lab and has no secondary ranges for Pods and
   Services. A VPC-native cluster needs those. Default to a purpose-built
   `rudder-gke-vpc` with documented primary and secondary CIDRs; do not silently
   graft cluster ranges onto lab networking.
4. Create the regional private GKE Standard cluster with separate node pools:
   system, build/platform, and customer workloads. Apply autoscaling bounds and
   resource limits from the start. Enable network policy enforcement **at creation**
   — on some clouds it cannot be turned on afterwards, and Phase 4's isolation
   guarantees are void without it.
5. Create private Artifact Registry repositories and allow only the build identity
   to push. Runtime workloads pull immutable digests only.
6. Delegate `rudder.invytt.com` to Cloud DNS: create the managed zone, then add its
   four NS records at GoDaddy, which currently serves `invytt.com` via
   `domaincontrol.com`. Delegating only the subdomain leaves the apex and existing
   records untouched. Verify with `dig NS rudder.invytt.com` before relying on it.
7. Define Terraform as the reviewed source of truth for all of the above. Manual
   console changes are emergency-only and must be backfilled into code.

**Exit criteria:** a clean GCP project can create the same cluster and
prerequisite services from reviewed infrastructure code, and
`dig NS rudder.invytt.com` returns Cloud DNS nameservers.

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
4. Permit an Ingress only for a service marked `public=true`; attach a
   cert-manager-issued certificate and a verified DNS name under
   `rudder.invytt.com`.
5. Keep database and cache ports off cloud load balancers, public node ports,
   and public firewall rules. Administrative access uses a documented,
   authenticated private path.
6. Enforce ResourceQuota and LimitRange for every Rudder environment; require
   requests and limits for app and worker workloads.

**Exit criteria:** private services work through DNS from allowed Pods and are
unreachable from the public Internet or another environment namespace.

### Step 5 — Durable state, observability, and recovery

1. Install the **CloudNativePG** operator in `rudder-system` and render database
   services as CNPG `Cluster` resources, replacing Phase 3's hand-rolled Postgres
   StatefulSet. Pin the operator version; treat its upgrade as a platform change,
   not a workload change. Redis stays a plain StatefulSet — it is a cache, and
   losing it is an availability event, not a data-loss event.
2. ~~Implement a small, separately authorised **backup identity broker**~~ —
   **implemented 2026-08-01.** At environment creation it creates one named
   Kubernetes ServiceAccount in the environment namespace, binds only that
   principal to the dedicated backup Google service account, and renders the
   CNPG `serviceAccountTemplate` plus `googleCredentials.gkeEnvironment: true`.
   It does not grant the node identity, every Pod in the cluster, or the
   control-plane identity general storage-write authority. CNPG scheduled base
   backups and continuous WAL archiving are rendered when a verified target is
   enabled. **Verified 2026-08-12:** the seven-day real GCS target completed a
   physical backup with continuous WAL archiving, then a separate non-public
   CNPG cluster restored that backup and passed a read-only catalog comparison
   before all disposable resources and its temporary identity grant were removed.
   Native Barman recovery is deprecated by CNPG and must migrate to the Barman
   Cloud Plugin before upgrading the operator to 1.31.
3. Enforce the stateful-data guardrails from section 3: RBAC denies PVC deletion
   to the control plane, stateful volumes retain on release, and environment
   teardown removes stateful volumes only via an explicit operator path.
4. Send control-plane audit logs, GKE events, application logs, metrics, and
   deployment state to the selected observability stack. Prometheus/Grafana can
   be interpreted by Rudder later; Phase 4 needs dependable raw signals first.
5. Define alerts for failed rollouts, no-ready-replica, ingress errors,
   exhausted quota, image-pull failure, certificate expiry, failed backup, and —
   new with CNPG — replication lag, failed WAL archive, and a Postgres failover
   election. An unarchived WAL segment is a silent data-loss window.

**Exit criteria:** an operator can identify which image, namespace, Pod, and
cloud identity served a deployment and can recover a tested data sample.

---

## 5. Provider-neutral boundary for future AWS and Azure

GCP is the first implementation, not the permanent product assumption. Keep
the Rudder core provider-neutral by exposing these capabilities instead of GCP
SDK calls throughout the control plane:

```text
CloudProvider
  ensure_cluster_target()                   # attach: resolve kubeconfig, do not create
  publish_image(digest)
  resolve_runtime_credentials()
  ensure_dns_record(host, target)           # zone provider is the seam, not the edge
  ensure_object_storage(spec)               # backup/WAL target, provider-specific WI
  observe_runtime(target, namespace)
```

Two capabilities the earlier draft listed are **not** in this contract, because
K8s-only ([ADR 0005](../decisions/0005-phase-4-kubernetes-only-attach-mode.md))
removed the need for them:

- `provision_managed_database` — Postgres is a CloudNativePG `Cluster` rendered by
  the shared workload adapter, identical on every cloud.
- `ensure_public_route` as a cloud call — the edge is ingress-nginx plus
  cert-manager, which are Kubernetes resources. Only the DNS record and the L4
  load balancer the controller's Service requests are cloud-touching, and the
  latter the cloud controller-manager handles for us.

The Kubernetes workload adapter remains shared. The GCP adapter maps these
capabilities to GKE, Artifact Registry, IAM/Workload Identity, Cloud DNS, and
the chosen Google edge/database/storage services. Future adapters map the same
contract to EKS/ECR/IAM/Route 53 and AKS/ACR/Managed Identity/Azure DNS.

Do not create AWS or Azure resources in Phase 4. Instead, write provider
contracts and acceptance tests so a later implementation can satisfy the same
behaviour without changing deployment records, UI semantics, or the service
graph.

### Cost of adding AWS and Azure

Audited 2026-07-29 against the current tree. The codebase is already largely
cloud-portable: the runtime layer makes **zero** GCP-specific service calls,
Kubernetes resources use standard APIs (`V1Ingress`, `V1PersistentVolumeClaim`,
`NetworkPolicy`) with no cloud-native annotations. The object-storage *contract*
is portable, while each cloud supplies its own short-lived workload identity;
cluster access goes through kubeconfig, and both ingress class and storage class
are configuration rather than constants.

**What does not change per cloud** — and this is most of the system: the
Kubernetes workload adapter, the Compose-derived service graph, immutable
deployment records, rollback and restore semantics, the UI, NetworkPolicy /
ResourceQuota / LimitRange rendering, and the object-storage contract.

**What does change per cloud:**

| Concern | GCP | AWS | Azure | Kind of work |
|---|---|---|---|---|
| Cluster credential exec | `gke-gcloud-auth-plugin` | `aws eks get-token` | `kubelogin` | code |
| Image registry + digest publish | Artifact Registry | ECR | ACR | code |
| Pod identity | Workload Identity | IRSA / EKS Pod Identity | Azure Workload Identity | code + IAM policy |
| Secrets backend | Secret Manager | Secrets Manager | Key Vault | code |
| DNS zone / ACME DNS-01 solver | Cloud DNS | Route 53 | Azure DNS | config |
| Storage class + expansion | `pd-*` | `gp3` via EBS CSI | `managed-csi` | config |
| NetworkPolicy prerequisite | on by default | needs VPC CNI policy or Calico | must be enabled at cluster creation | config, but a silent security gap if missed |
| Backup / WAL target | GCS | S3 | Blob (S3 API via gateway, or a second client) | mostly config |

K8s-only ([ADR 0005](../decisions/0005-phase-4-kubernetes-only-attach-mode.md))
removed two rows that would otherwise sit here. **Public edge and certificates** are
now identical on all three clouds — ingress-nginx plus cert-manager, no ALB
Controller, no ACM, no AGIC, no Google-managed certificates. **The database** is a
CloudNativePG `Cluster` rendered by the shared adapter, so RDS and Azure Database
never enter the picture. That is the concrete payoff of the K8s-only mandate: the
two most cloud-divergent, most code-heavy seams collapse into shared Kubernetes
manifests.

Two very different scopes follow from the cluster-ownership decision:

**Attach mode** — the operator provisions the cluster, Rudder consumes a
kubeconfig and owns only namespaces and workloads.

| Work | Estimate |
|---|---|
| Phase 4 as specified (GKE) | 3–5 wk |
| Harden `CloudProvider` into a real contract plus a cloud-agnostic conformance suite | +1–2 wk |
| AWS/EKS adapter | +2–3 wk |
| Azure/AKS adapter | +2–3 wk |
| **All three clouds, attach mode** | **8–13 wk total** |

**Provision mode** — Rudder owns cluster lifecycle: create, upgrade, delete,
node pools, VPC, identity federation.

| Work | Estimate |
|---|---|
| Attach-mode baseline above | 8–13 wk |
| Cloud-agnostic cluster lifecycle model: `Cluster` entity, create/upgrade/delete state machine, credential storage, drift detection | +2–3 wk |
| Per-cloud provisioning IaC, teardown, and upgrade tests (×3) | +6–9 wk |
| **All three clouds, provision mode** | **16–25 wk total** |

Provision mode also carries permanent costs that a one-time estimate hides: CI
must create and destroy real clusters across three clouds for every acceptance
run (real money per run), three Kubernetes version-skew streams to track, and
three sets of cloud-specific failure modes — quota denials, region capacity,
per-cloud IAM propagation delays — that become Rudder's on-call surface rather
than the operator's.

**Recommendation:** ship Phase 4 in attach mode, and treat the conformance suite
as part of Phase 4 rather than a later cleanup. Attach mode is where the
portability the audit found actually pays out; provision mode is a separate
product decision, not an extension of this phase.

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

The executable acceptance procedures and evidence format are in
[the Phase 4 GKE operations runbook](../runbooks/PHASE-4-GKE-OPERATIONS.md).

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

- [x] GKE Standard cluster and dependencies are reproducible from reviewed
      infrastructure-as-code.
- [x] Rudder deploys immutable Artifact Registry images into labelled GKE
      environment namespaces.
- [x] Workload Identity, least-privilege RBAC, and secret access are verified.
- [x] Default-deny isolation is active; only explicitly allowed private traffic
      works.
- [x] Only explicitly public application services receive managed HTTPS routes.
- [x] Databases, caches, workers, queues, and internal observability services
      have no public endpoint.
- [x] A broken candidate leaves the prior live URL serving traffic.
- [x] Immutable restore reuses a recorded digest and does not rebuild.
- [x] A safe GKE node drain evicts a PDB-permitted replica and restores full
      redundancy after uncordon; the public control-plane endpoint remains available.
- [x] Point-in-time recovery, failed-rollout, secret-rotation, and DNS/certificate
      runbooks are written and exercised.
- [x] Cloud Monitoring log- and metric-based alert policies plus the
      incident-response runbook are implemented and exercised with an isolated
      image-pull failure. Notification channels are a reviewed operator input,
      not committed recipient metadata.
- [x] Controlled-beta workloads use the reviewed shared, tainted platform-pool
      contract. A dedicated workloads pool is explicitly deferred to the
      post-Phase capacity expansion described above.
- [x] The Phase 4 checkpoint documents the exact cluster configuration,
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
- [ADR 0004](../decisions/0004-kubernetes-networking-replaces-wireguard-mesh.md)
  records the mesh cancellation and the deprecated `wg_*` fields.
- Documentation alignment is **done** (2026-07-29): `docs/PRD.md`,
  `docs/phases/README.md`, `PHASE-3-kubernetes-runtime.md`,
  `PHASE-5-environments.md`, `PHASE-6-operations.md`,
  `PHASE-7-frontends.md`, and `docs/NEED-FROM-YOU.md` no longer describe this
  file as the legacy WireGuard alternative.
- Remaining code debt from the cancellation, to clear during Phase 4. The subnet
  allocator is still **live**, not dormant — every environment create calls it and
  the API publishes the result — so removing it is a real change, not a delete of
  unreachable code:
  - `control-plane/rudder_cp/services/environments.py` — remove
    `allocate_wg_subnet`, `SUBNET_POOL_EXHAUSTED`, the subnet pool constants, and
    the `wg_subnet=` argument in `create_environment`.
  - `control-plane/rudder_cp/schemas/environment.py` — drop `wg_subnet` from
    `EnvironmentRead` (breaking response change, accepted in ADR 0004).
  - `control-plane/rudder_cp/routers/environments.py` — drop the "`wg_subnet` is
    server-owned" text from the PUT description.
  - `control-plane/tests/test_crud.py` — delete
    `test_every_environment_gets_a_distinct_wg_subnet` and
    `test_wg_subnet_reuses_a_freed_slot`, and drop `wg_subnet` from the
    replace-fields assertion.
  - `control-plane/rudder_cp/models/project.py` — fix the docstring claiming
    `wg_subnet` provides environment isolation. The column itself stays nullable
    and unset per ADR 0004.
