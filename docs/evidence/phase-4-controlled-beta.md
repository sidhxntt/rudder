# Phase 4 controlled-beta evidence

> **Evidence boundary:** this page preserves point-in-time GKE evidence
> recorded through 2026-08-15. It supports a controlled-beta architecture
> claim, not general availability, unlimited capacity, exact cloud spend, or a
> hardened multi-tenant service.

## Environment under test

The reference environment was one private-node regional GKE Standard cluster
in `asia-south1`. It used an untainted system pool and a tainted platform pool.
Rudder platform components and controlled-beta workloads shared explicitly
selected platform capacity; the optional dedicated workloads pool remained
disabled behind the quota gate.

Terraform owned the GCP foundation. Rudder attached to that cluster and owned
environment namespaces and workload resources, not cluster creation, upgrades,
node-pool resizing, or deletion.

## Recorded acceptance evidence

The controlled-beta record covered:

- a real GitHub App delivery producing an environment-scoped release;
- Cloud Build publishing an immutable Artifact Registry digest;
- application, Redis, and PostgreSQL readiness in the environment namespace;
- public HTTPS returning `200` through ingress-nginx, Cloud DNS, ExternalDNS,
  and cert-manager;
- rollback to a stored immutable deployment without rebuilding the image;
- a deliberately broken candidate preserving the previously healthy route;
- CloudNativePG backup, full restore, and point-in-time recovery drills;
- cross-namespace TCP denial and private database/cache/worker exposure;
- normal node drain, database eviction protection, and recovery;
- metrics, alert-policy, secret-rotation, DNS, and certificate checks.

The repository retains the implementation and automated contract tests behind
these paths. Repeating the live drills still requires valid GCP credentials,
DNS delegation, a running cluster, and sufficient quota.

## Capacity result

The decisive capacity constraint was project-wide `CPUS_ALL_REGIONS`: 12 vCPUs
were used out of 12. A regional three-zone `e2-standard-2` pool requires six
vCPUs, so adding a dedicated workloads pool was not safe. The documented next
gate is at least 18 total vCPUs, with 24 recommended for operating headroom,
followed by repeated placement, route, backup, and isolation verification.

This is one cluster with regional node-pool capacity. The number six describes
vCPUs for one pool; it does not describe six GKE clusters.

## Remaining gates

- Keep the shared-pool controlled-beta contract until quota and cost allow a
  dedicated workloads pool.
- Repeat backup restore and point-in-time recovery rather than inferring
  recoverability from successful backup creation.
- Configure and exercise real alert notification channels.
- Re-run private endpoint, RBAC, NetworkPolicy, secret, and workload identity
  checks whenever platform service types expand.
- Treat organization models, tenant billing, hostile-workload isolation,
  AWS/EKS, and Azure/AKS as future work.

See [Phase 4](../phases/phase-4.md), [GKE operations](../gke-operations.md),
and the [multi-cloud guide](../multi-cloud.md) for architecture and operating
context.
