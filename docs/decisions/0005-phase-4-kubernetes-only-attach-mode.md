# ADR 0005 — Phase 4 is Kubernetes-only, attach mode, CloudNativePG

**Date:** 2026-07-29
**Status:** Accepted
**Builds on:** [ADR 0004](0004-kubernetes-networking-replaces-wireguard-mesh.md)

## Context

Phase 4 needed four decisions recorded before any GCP resource is provisioned. The
draft phase document recommended Cloud SQL for customer data and left cluster
ownership, the public edge, and the public hostname open.

The operating constraint, stated by the project owner: **everything Rudder runs is
managed by Kubernetes, including in production.** This is consistent with the
Phase 3 design, which already chose in-cluster portable primitives over managed
GCP services, and it is what keeps the EKS/AKS adapters cheap — every component
moved into the cluster is covered by the shared workload adapter instead of
becoming a per-cloud seam.

## Decisions

1. **Kubernetes-only in production.** Managed cloud services are used only where
   nothing can run in-cluster by nature: the L4 load balancer fronting ingress,
   object storage, the image registry, and the workload identity that reaches those
   two. Everything else — application, worker, database, cache, ingress
   controller, certificate issuance — runs as Kubernetes workloads.

2. **Attach mode.** Terraform provisions one shared regional GKE cluster; Rudder
   consumes a kubeconfig and owns only namespaces and the workloads inside them.
   Rudder does not create, upgrade, or delete clusters or node pools. Estimated
   8–13 weeks for all three clouds, against 16–25 for provision mode.

3. **CloudNativePG for Postgres.** Database services render as CNPG `Cluster`
   resources, not the hand-rolled StatefulSet Phase 3 produces. CNPG supplies
   streaming replication, failover election, PITR via WAL archiving, and scheduled
   backups. A plain StatefulSet is acceptable for acceptance testing only and must
   never hold customer data. Redis stays a plain StatefulSet — it is a cache.

4. **Portable edge.** ingress-nginx as the single ingress controller and
   cert-manager with Let's Encrypt for certificates, in preference to GKE Gateway
   and Google-managed certificates. Both run in-cluster and move to EKS and AKS
   unchanged.

5. **Public hostnames under `rudder.invytt.com`**, delegated from GoDaddy to a
   Cloud DNS managed zone. Only the subdomain is delegated, leaving the `invytt.com`
   apex and its existing records untouched.

## Consequences

- Saves roughly $50–150/month against Cloud SQL and removes a GCP dependency.
- Transfers real operational burden to Rudder: Postgres version upgrades, WAL
  archive correctness, failover verification, replication-lag monitoring,
  connection pooling, and restore drills.
- **The asymmetric risk is data loss, not downtime.** Rudder's own reconciler
  deleting a StatefulSet's PVC destroys customer data unrecoverably; a managed
  service's independent lifecycle would have prevented it. Two controls are
  therefore mandatory rather than optional:
  1. WAL archiving to object storage plus a restore drill actually executed
     against a disposable dataset.
  2. The control plane must be structurally unable to delete a stateful PVC —
     RBAC denies PVC deletion, stateful volumes retain on release, and teardown of
     stateful volumes goes through an explicit separately-authorised operator path.
- Adds two pinned platform dependencies to install and version: the CloudNativePG
  operator and cert-manager. Their upgrades are platform changes, not workload
  changes.
- Attach mode means Rudder cannot self-serve a new cluster or region. Accepted:
  no requirement exists for it, and provision mode remains addable later without
  changing deployment records or UI semantics.
- Four cloud seams survive per additional cloud even under K8s-only: credential
  exec plugin, registry, pod identity, and DNS zone provider. The list is shorter
  than with managed databases, not empty. See `docs/phases/PHASE-4-gke-production-runtime.md` →
  "Cost of adding AWS and Azure".
