# Phase 4 — GKE landing zone and controlled-beta production path

> **Evidence status:** controlled-beta core path recorded complete through
> 2026-08-15. This is not a claim of unlimited general-customer production
> capacity; the dedicated workloads pool remains a post-phase expansion.

## Why GKE and what was planned

Phase 3 proved a portable Kubernetes contract. Phase 4 carried the same
namespace/workload/service/route model onto a real GCP landing zone and added
what a laptop cannot: private Artifact Registry builds, regional GKE Standard,
Workload Identity, public HTTPS/DNS, object-storage backup and restore,
monitoring, infrastructure as code, and operational drills.

The design chose **attach mode**: Terraform provisions one shared regional
cluster and Rudder consumes it, owning namespaces and workloads rather than
creating/upgrading clusters or node pools. The attach-mode decision is
explained in the [architecture guide](../architecture.md). This was faster and lower risk than self-service
provisioning, while keeping an eventual EKS/AKS path viable.

## Architecture implemented

```text
GitHub App push or Rudder UI
  -> control plane -> Cloud Build -> Artifact Registry immutable digest
  -> GKE namespace rudder-<environment-id>
     -> app Deployment -> ClusterIP Service -> ingress-nginx -> HTTPS
     -> private worker, Redis, PostgreSQL/CNPG, Secrets, PVCs, policies
  -> ExternalDNS + Cloud DNS; cert-manager + ACME certificate
```

The regional `rudder-gke` cluster in `asia-south1` has an untainted system pool
and tainted platform pool (`rudder.pool=platform:NoSchedule`). Rudder platform
and controlled-beta environment workloads use an explicit matching selector and
toleration. Public exposure is limited to labelled public application ingress
and the control plane; databases, Redis, worker, and backup broker endpoints
remain private.

### Security and environment boundaries

- Artifact Registry accepts immutable digests rather than mutable tags.
- GKE Workload Identity replaces JSON keys and broad node identities.
- Namespace-level quota, limits, default-deny policies, private Services, and
  scoped ServiceAccounts separate environments.
- ExternalDNS observes Rudder-labelled Ingresses and writes TXT ownership
  records in the delegated DNS zone only.
- External Secrets reads a designated Secret Manager container; runtime
  secrets never belong in Terraform values, Git, shell history, or logs.
- CNPG backup identity binding is brokered: the control plane cannot directly
  write IAM policy; a private broker validates generated namespace/service
  account bindings before granting the narrow workload identity.

## Stateful data and operational design

PostgreSQL uses CloudNativePG rather than a plain StatefulSet in production.
It supplies replication, WAL archiving, scheduled backup, full restore, and
point-in-time recovery. Redis remains a cache-oriented StatefulSet. Avoiding a
managed Cloud SQL dependency reduced the expected service bill, but transferred
operations to Rudder: pinned operator upgrades, restore drills,
replication/lag monitoring, and strict prevention of accidental PVC deletion.

Backup uses GCS and a dedicated identity. The broker needs a project-level
three-permission IAM role because Google IAM cannot scope `setIamPolicy` to one
service account; private networking, caller validation, exact-member checks,
and bucket-only backup permissions are compensating controls. This residual
scope is explicit and should be audited, not described as perfect isolation.

## Cost and capacity decisions

The biggest recorded GCP constraint was project-wide `CPUS_ALL_REGIONS`, which
was 12 used of 12, even though regional CPU display could look larger. A
three-zone e2-standard-2 workloads pool requires more capacity, so it was not
silently created. The controlled-beta compromise is shared tainted platform
compute, not dedicated workload compute. A dedicated workload pool requires
quota increase (at least 18 vCPUs; 24 recommended), Terraform enablement,
workload-pool selection, and repeated placement/route/backup/isolation tests.

Cost drivers include GKE node pools/control plane, load balancer and public IP,
Artifact Registry storage/egress, Cloud Build minutes and source/log buckets,
Cloud DNS, GCS backup/WAL retention, and observability/alerting. Attach mode
reduces provisioning scope but does not eliminate these operational costs.

## Failure modes and resolutions

| Issue | Resolution |
| --- | --- |
| Failed immutable candidate could affect live traffic | Candidate readiness is required before ingress promotion; a recorded broken-image drill retained the old backend. |
| DNS/cert/config could be wrong despite a ready Pod | Bootstrap fails closed on secret sync, database readiness, migration, image digest, hostname, and DNS prerequisites. |
| Backup identity could be over-broad | Per-environment generated identity plus private broker and scoped GCS access; no static S3/HMAC or service-account key. |
| Node drain risks database availability | CNPG replicas and PDB policy were drilled with a normal eviction and recovery. |
| Cluster capacity unavailable | Keep the reviewed shared-pool contract; do not weaken isolation or manually mutate cluster state. |

## Recorded evidence

The [Phase 4 controlled-beta evidence record](../evidence/phase-4-controlled-beta.md)
records a real GitHub App deployment to an environment namespace, Cloud Build
publication of an Artifact Registry digest, application/
Redis/Postgres readiness, HTTPS `200`, and rollback to stored immutable
deployments without rebuild. Later drills recorded GCS backup, full restore,
PITR, cross-namespace TCP denial, failed-candidate continuity, node drain,
metrics/alert checks, secret rotation, and DNS/certificate health.

## Limits and forward work

This is a controlled-beta platform, not proof that every future workload type
is safe. Follow the [GKE operations guide](../gke-operations.md), repeat
private-endpoint and policy audits as service types expand;
keep exercising restore rather than assuming backups work; configure alert
notification channels; and create the dedicated workloads pool only after the
authoritative quota gate passes. AWS and Azure mappings must preserve the
Kubernetes resource contract while replacing the registry, identity, DNS, and
object-storage seams—those mappings are documented outside this phase.
