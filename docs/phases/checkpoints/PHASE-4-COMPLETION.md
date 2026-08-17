# Phase 4 — GKE core delivery-path verification

**Verified:** 2026-07-31; updated with operational evidence through 2026-08-15

**Branch:** `phase-4`

**Result:** The core GKE deployment path, GCS backup/full-restore, public TLS,
and deployed-environment isolation are verified. Phase 4 remains open only for
the hardening gates listed at the end of this checkpoint.

## What was verified

The production control plane runs on the regional GKE Standard cluster
`rudder-gke` in `asia-south1`. Its GKE runtime has Workload Identity, an
Artifact Registry-backed immutable-image build path, and an HTTPS public edge
under `rudder.invytt.com`.

The test application was imported from the installed GitHub App repository
`sidhxntt/rudder-import-test-20260724` and deployed to:

- Project: `5752f902-c035-4084-9436-e73cc29591de`
- Environment: `b7c60f6b-fc8a-4c62-82bc-f35a87174b13`
- Namespace: `rudder-b7c60f6bfc8a`
- Public host: `rudder-import-test-20260724-2.production.rudder.invytt.com`

## End-to-end proof

| Check | Evidence | Result |
| --- | --- | --- |
| GitHub App automatic deploy | Empty verification push `106b06e83c903352050942790f1b8569d9de62f7` created deployment `71ffeadd-3472-4f8c-83bd-7166bcec8f8a` | Passed |
| Immutable build | Deployment used Artifact Registry digest `sha256:276e8a8913f15dab0cd8553d364729e3d4dbec5a20cd5ecc864b24f2f9f9c83a` | Passed |
| Kubernetes readiness | `app-71ffeadd` Deployment, Redis StatefulSet, and Postgres workload were Ready | Passed |
| Public route | HTTPS request to the application host, resolved to the GKE ingress IP, returned `200` and `{"status":"ok","service":"rudder-import-test"}` | Passed |
| Immutable restore | Restored `55e3378e-c567-402e-a2ee-cb73ae02ce34`, then restored the newest deployment `71ffeadd-3472-4f8c-83bd-7166bcec8f8a` | Passed |
| No rebuild on restore | Deployment history stayed at six records throughout the restore operations | Passed |

The newest deployment is live; the prior deployment is superseded. Kubernetes
shows the live application image as a digest, never a mutable tag.

## How to re-verify

Do not copy secrets to shell history. Obtain an admin access token through the
normal local operator environment, then query the deployment API. For the
application route, test the public hostname normally. If a developer machine
still has a cached pre-delegation NXDOMAIN response, temporarily resolve its
hostname to the ingress IP only for diagnostic purposes; public resolvers and
Cloud DNS remain the authority.

```text
GitHub push
  -> GitHub App webhook
  -> https://api.rudder.invytt.com/webhooks/github
  -> regional Cloud Build
  -> Artifact Registry immutable digest
  -> GKE namespace release
  -> cert-manager / ExternalDNS / ingress
  -> public HTTPS application route
```

For cluster-side evidence, inspect the environment namespace:

```bash
kubectl -n rudder-b7c60f6bfc8a get deploy,statefulset,pods -o wide
kubectl -n rudder-b7c60f6bfc8a get ingress,certificate,service
```

## Important operating constraints

- The test cluster currently uses the shared, tainted `platform` node pool.
  A dedicated customer workloads pool remains blocked until aggregate GCP CPU
  quota is available.
- GitHub OAuth authenticates a user; the GitHub App webhook is the source of
  automatic deployment events. Both must be configured for the selected
  repository.
- Cloud Build source and build logs are stored in dedicated private GCS buckets.
  They are durable; UI log aggregation across control-plane replicas is an
  operations improvement, not evidence that a build did or did not run.
- The public route must be health-checked before marking a release live. An
  image build alone is not a successful deployment.

## Operational evidence added 2026-08-12

- [x] The GCS-backed CNPG Backup `postgres-backup-4202aa0c-9d49-4ddb-b342-7b25ead99ad3`
      completed using the generated per-environment Workload Identity binding.
      Continuous WAL archiving and `LastBackupSucceeded` were both `True`.
- [x] A separate non-public CNPG recovery cluster restored the completed GCS
      backup, reached `Ready`, and matched the production catalog (`app,postgres`
      and public-table count `0`). Its PVC, ServiceAccount, NetworkPolicy, and
      temporary Workload Identity binding were deleted afterward.
- [x] The public app and `api.rudder.invytt.com/healthz` returned HTTPS `200`
      with HSTS; both certificates were Ready.
- [x] A bounded TCP probe from a second environment namespace to the first
      environment's PostgreSQL service timed out, proving default-deny isolation.

## Controlled-beta acceptance — completed 2026-08-15

- [x] A disposable CloudNativePG **point-in-time recovery** Cluster restored
      the `included-2` row written before PostgreSQL target time
      `2026-08-15 06:00:23.097744+00`, while correctly excluding `excluded-2`
      written afterwards. The recovery Cluster, PVC, ServiceAccount,
      NetworkPolicy, Workload Identity member, and source drill table were all
      removed after verification.
- [x] Baseline private-endpoint/default-deny audit completed 2026-08-15: the
      only Ingress hosts are the two explicitly public apps and the control
      plane. Customer PostgreSQL and Redis, the backup broker, and control-plane
      database services are ClusterIP or ExternalName only; both customer
      namespaces retain `rudder-private-network`. Repeat this audit for every
      new service type and quarterly using the operations runbook.
- [x] Deliberately broken immutable-image candidate
      `17055e6f-34ac-4186-af1e-17a79395fb84` failed readiness and was cleaned
      up without changing the live Ingress backend (`app-f65415b3`). The
      existing public endpoint continued its normal unauthenticated `401`
      response throughout the drill.
- [x] Drained platform node `gke-rudder-gke-platform-14fea6d6-2b3x` using
      normal eviction. Its non-primary CNPG replica was evicted under the
      one-disruption PDB allowance; the remaining primary and replica, plus
      `api.rudder.invytt.com/healthz`, stayed available. After uncordoning, the
      replica returned and the three-instance CNPG Cluster was Ready again.
- [x] Logs, metrics, alert, secret-rotation, DNS/certificate, and incident
      runbooks are documented and exercised. Terraform created Cloud Monitoring
      policies `Rudder GKE container restarts` and `Rudder GKE candidate image
      pull failure`; the latter opened alert
      `projects/invytt-2483d/alerts/0.obgjxyyy7o9l` at `2026-08-15T07:01:34Z`
      from an isolated invalid-image Pod in `rudder-system`. The Pod was then
      deleted. The restart metric query returned a live time series. Notification
      routing is parameterized as `alert_notification_channels`; it is empty
      until an operator configures a recipient.
- [x] The shared, tainted `platform` pool is the accepted controlled-beta
      topology. Customer workloads retain the reviewed platform selector and
      toleration; this is an explicit capacity trade-off, not a claim of
      dedicated compute isolation.

The secret-rotation, DNS, certificate, and failed-rollout parts of the
operations runbook were exercised on 2026-08-15. A short-lived Secret Manager
secret synchronized through the scoped External Secrets identity; a forced
refresh changed the redacted SHA-256 of the synced Kubernetes value, and every
temporary Secret Manager/Kubernetes resource was deleted. ExternalDNS reported
all records current and all managed Certificates were Ready. The alert incident
and runtime metric evidence above completes the logs/metrics alert exercise.

## Post-Phase capacity expansion (not a Phase 4 exit criterion)

Create the dedicated regional customer workloads pool only after project-wide
`CPUS_ALL_REGIONS` quota reaches at least 18 vCPUs (24 recommended). Then set
`enable_workloads_pool=true`, apply the reviewed Terraform plan, switch
`RUDDER_KUBERNETES_WORKLOAD_POOL` to `workloads`, and repeat the placement,
route, backup, and isolation checks. This controlled-beta acceptance does not
make the shared-pool cluster a general customer-production service.
