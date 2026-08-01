# Phase 4 — GKE core delivery-path verification

**Verified:** 2026-07-31

**Branch:** `phase-4`

**Result:** The core GKE deployment path is verified. Phase 4 itself remains
open pending the hardening gates listed at the end of this checkpoint.

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

## Still required before closing Phase 4

- [ ] Execute and record a CloudNativePG backup and point-in-time restore drill
      using the narrowly scoped per-environment Workload Identity broker.
- [ ] Prove default-deny NetworkPolicy isolation between two environment
      namespaces and verify that Postgres, Redis, workers, queues, and metrics
      have no public endpoint.
- [ ] Exercise a deliberately broken GKE candidate while continuously checking
      the previous public URL.
- [ ] Drain or lose a GKE node and verify Kubernetes rescheduling plus public
      route continuity to the stated SLO.
- [ ] Complete logs, metrics, alerts, secret-rotation, DNS/certificate, and
      incident runbooks and exercise them.
- [ ] Create the dedicated customer workloads node pool after the project-wide
      `CPUS_ALL_REGIONS` quota permits it.

Until those gates pass, do not call Phase 4 fully complete or offer the shared
GKE cluster as a general customer-production service.
