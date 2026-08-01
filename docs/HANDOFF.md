# Rudder handoff — resume from Phase 4

This document is the starting point for a new Codex session. Read it before making changes. It is deliberately operational: it records what is real, what is pending, and how to validate the next slice without exposing credentials.

## First instruction for a new session

When the user says “scan and understand my codebase”, do this in order:

1. Read this file completely.
2. Read `docs/phases/README.md`, then `docs/phases/PHASE-4-mesh.md`.
3. Inspect the current branch and dirty worktree:

   ```sh
   git branch --show-current
   git status --short
   git log --oneline -12
   ```

4. Do **not** reset, clean, remove containers, reset databases, or commit unrelated files. This repository is commonly left with in-progress work and local state.
5. Inspect the files named in “Current code in progress”, run the focused tests, then verify external GCP state before changing infrastructure.

The current branch at the time of this handoff is `phase-4`. Phase 4 is in progress; do not claim it is completed merely because the cluster exists or platform Pods are healthy.

## Product and phase map

Rudder is a Railway/Vercel-like deployment platform:

- `web/` is the Next.js product UI (normally `http://localhost:3000`).
- `control-plane/` is the FastAPI API and orchestration engine (normally local `:8000`).
- `agent/` is the Docker execution agent used by the earlier local/multi-host runtime.
- `infra/` contains Terraform, Kubernetes manifests, and production scripts.

Completed/merged work:

- **Phase 1** — single-host Docker/Compose deployment, GitHub import flow, UI and rollback foundations.
- **Phase 2** — agent registration/heartbeats, scheduler, reconciler, multi-host proof on GCP VMs.
- **Phase 3** — local Kubernetes runtime using Kind, Kubernetes release rendering, local verification.

Current work:

- **Phase 4** — production GKE runtime and shared platform pool. The authoritative plan and acceptance criteria are in `docs/phases/PHASE-4-mesh.md`.

Future documented phases:

- **Phase 5** — environments.
- **Phase 6** — operations/hardening.

## Current Phase 4 objective

Move the Kubernetes execution path from local Kind to production GKE safely. Rudder should build an immutable image, schedule it to GKE, create private Kubernetes services/stateful services, expose only intended public routes, and retain a safe recovery path.

The intended production topology is:

```text
GitHub push -> Rudder webhook/control plane -> Cloud Build -> Artifact Registry
                                          -> GKE release -> private Kubernetes services
                                                           -> public ingress for selected app services
```

Kubernetes networking replaces the old WireGuard-mesh idea for the GKE path. The architectural decisions are documented in:

- `docs/decisions/0004-kubernetes-networking-replaces-wireguard-mesh.md`
- `docs/decisions/0005-phase-4-kubernetes-only-attach-mode.md`

## Verified GCP/GKE state (re-check; do not assume)

Non-secret identifiers:

- GCP project: `invytt-2483d`
- Region: `asia-south1`
- GKE cluster: `rudder-gke` (Standard GKE)
- Expected context: `gke_invytt-2483d_asia-south1_rudder-gke`
- Workload Identity pool: `invytt-2483d.svc.id.goog`
- Artifact Registry repository: `asia-south1-docker.pkg.dev/invytt-2483d/rudder`
- Backup bucket: `invytt-2483d-rudder-backups`
- Build source/log buckets: `invytt-2483d-rudder-build-source` and `invytt-2483d-rudder-build-logs`

Start each cloud session with read-only checks:

```sh
gcloud config get-value project
gcloud container clusters describe rudder-gke --region asia-south1 --project invytt-2483d \
  --format='json(status,location,nodePools,workloadIdentityConfig)'
kubectl config current-context
kubectl get nodes
kubectl get pods -A
```

Capacity constraint: the project regional CPU quota was tight (historically `CPUS_ALL_REGIONS` was 12/12). Customer runtime Pods currently share the platform node pool through the configured selector/toleration. Do **not** add a workload node pool or increase nodes without first inspecting quota and obtaining user approval.

The prior deployed control-plane image was pinned to an immutable Artifact Registry digest. Always use a digest when rolling out; never use a mutable tag for a production validation.

## Current code in progress

The worktree is intentionally dirty and includes Phase 4 implementation and tests. Key areas:

- `control-plane/rudder_cp/runtime/kubernetes.py`
  - GKE/Kubernetes release rendering.
  - CloudNativePG cluster and ScheduledBackup resource support.
- `control-plane/rudder_cp/runtime/targets.py`
  - maps configuration to the Kubernetes runtime.
- `control-plane/rudder_cp/runtime/backup_identity.py`
  - backup identity broker client and constrained Google IAM operations.
- `control-plane/rudder_cp/backup_broker.py`
  - private in-cluster FastAPI broker for per-environment CloudNativePG service-account binding.
- `control-plane/rudder_cp/config.py`
  - runtime settings, including backup schedule.
- `infra/kubernetes/platform/control-plane.yaml`
  - control-plane deployment configuration.
- `infra/kubernetes/platform/backup-identity-broker.yaml`
  - private two-replica broker, NetworkPolicy, and workload identity.
- `infra/gcp/terraform/`
  - cluster, Artifact Registry, Cloud Build, storage, service accounts and least-privilege broker role.
- `infra/gcp/scripts/`
  - preflight, bootstrap, `kubectl` configuration, and verification helpers.

Backup implementation currently designed:

- CloudNativePG `ScheduledBackup` is rendered for managed PostgreSQL.
- Default schedule is `0 0 2 * * *` (the six-field CloudNativePG cron form: daily at 02:00 UTC).
- PostgreSQL retention defaults to seven days when GCS backup is configured.
- Each customer environment gets a generated Kubernetes service account; the private broker binds it to the dedicated GCS backup Google service account.
- The broker has a narrowly scoped custom IAM role containing only `iam.serviceAccounts.get`, `iam.serviceAccounts.getIamPolicy`, and `iam.serviceAccounts.setIamPolicy`.
- The broker only accepts Rudder-generated namespaces/service-account names; it is private and NetworkPolicy-restricted to labelled control-plane Pods.

Do not replace this with a project-wide broad IAM admin role. Google does not allow `setIamPolicy` to be narrowed directly to one target service account, which is why the isolated broker exists.

## Latest build that must be checked first

An in-progress Cloud Build was started immediately before this handoff:

- Build ID: `a5231ca8-b71b-4466-b7f9-c2221ce36c27`

Check it before submitting another build:

```sh
gcloud builds describe a5231ca8-b71b-4466-b7f9-c2221ce36c27 \
  --project invytt-2483d --region asia-south1 \
  --format='json(status,statusDetail,results.images,logUrl)'
```

If successful, resolve the immutable image digest from build results/Artifact Registry. Roll out that digest to both the control plane and backup broker; do not deploy a mutable tag.

The intended Cloud Build pattern uses the dedicated build service account and private source/log buckets:

```sh
gcloud builds submit . \
  --project invytt-2483d --region asia-south1 \
  --tag <artifact-registry-image-tag> \
  --service-account projects/invytt-2483d/serviceAccounts/<build-service-account> \
  --gcs-source-staging-dir gs://invytt-2483d-rudder-build-source/manual \
  --gcs-log-dir gs://invytt-2483d-rudder-build-logs/manual
```

Do not paste account credentials, OAuth secrets, GitHub App private keys, webhooks secrets, API keys, or personal tokens into code, docs, shell history, commits, or chat.

## Safe validation sequence from here

1. **Inspect before changing anything.** Confirm git state, build status, cluster state, quota, and whether the existing deployments are healthy.
2. **Run focused tests for the uncommitted runtime change.**

   ```sh
   cd control-plane
   uv run pytest \
     tests/test_kubernetes_runtime.py \
     tests/test_gke_target.py \
     tests/test_gke_backup_settings.py \
     tests/test_gke_backup_broker.py \
     tests/test_gke_backup_identity_contract.py -q
   uv run ruff check rudder_cp/runtime/kubernetes.py rudder_cp/runtime/targets.py rudder_cp/config.py \
     tests/test_kubernetes_runtime.py tests/test_gke_target.py
   ```

3. **Validate Terraform before planning/applying.**

   ```sh
   cd ../infra/gcp/terraform
   terraform fmt -check
   terraform validate
   ```

4. **Roll out only after an immutable image is available.** Update the platform manifests with the digest and required non-secret runtime settings, then target-apply the control plane and broker. Avoid blindly running broad bootstrap commands: they can reconcile unrelated platform components and create capacity/PDB pressure.
5. **Verify the platform.** Wait for both deployments, check Pod readiness, confirm the broker health endpoint from inside the cluster/control-plane Pod, and inspect environment variable names only—not secret values.
6. **Run the actual acceptance drill through Rudder.** Create a disposable GKE environment containing a managed PostgreSQL service. Verify:
   - generated namespace and service account;
   - private CloudNativePG cluster/service;
   - generated `ScheduledBackup` with expected cron/retention;
   - backup identity binding contains only the generated service-account member;
   - a manual backup initiated via Rudder completes and writes backup/WAL objects to the GCS bucket.
7. **Perform a disposable restore drill.** Use the installed CloudNativePG version and its current official recovery API to create a recovery Cluster from the backup/PITR data. Verify seeded data, then delete the recovery workload/namespace and clean up according to retention policy. Do not guess a recovery CRD manifest.
8. **Validate ingress, public DNS/certificates, namespace isolation, and basic operations.** Only then may Phase 4 be described as complete.

CloudNativePG backup documentation to consult before writing recovery manifests: <https://cloudnative-pg.io/docs/>. ScheduledBackup uses a six-field cron and supports `backupOwnerReference: self`.

## Why Phase 4 is not complete yet

These are mandatory remaining gates:

- Deploy the current broker/ScheduledBackup code to GKE using a verified immutable image.
- Verify a real CloudNativePG workload gets the generated identity binding and scheduled backup.
- Prove GCS backup objects are produced.
- Perform one disposable recovery/restore drill.
- Confirm public routing, TLS/DNS, isolation, and operational behaviour for the deployed workload.

Existing Kind/local success and platform Pod readiness are useful, but they are not substitutes for the GKE backup-and-restore acceptance test.

## Local development notes

- UI: `web/`, normally `localhost:3000`.
- API: `control-plane/`, normally `localhost:8000`.
- Local Kubernetes: Kind cluster `rudder-kind`.
- Common make targets include `make kind-up`, `make verify-kind`, and `make reset-local`.

`make reset-local` and container/database cleanup are destructive. Never run them just to fix a UI view; get explicit user approval first. Old UI deployment/project history and stale local Docker resources may exist from prior experiments.

GitHub OAuth signs the user in. GitHub App access lists repositories; webhook delivery triggers redeployment. A local webhook receiver needs a public tunnel. Production must use the public control-plane endpoint. Keep all associated secrets in environment/secret managers only.

## Common pitfalls observed in prior work

- A green Docker container is not proof that Rudder’s control-plane state, logs, or ingress are correct. Check the actual runtime status and route.
- Avoid auto-deploy loops: a webhook should trigger one deployment per delivery/commit, with deduplication and immutable artifacts.
- A rollback should repoint/release a prior immutable artifact; it should not rebuild source.
- Do not treat all Compose-managed child services as independently built application images; they share a release lifecycle.
- Do not expose PostgreSQL, Redis, or internal worker services publicly by default.
- Do not use a broad project IAM admin grant as a shortcut for database backup identities.
- The GKE node pool has constrained CPU capacity. Always inspect quota and scheduling state first.
- Stale Next.js `.next` artifacts can cause missing vendor-chunk errors locally; stop the dev server, remove only the generated `.next` directory if necessary, then restart. Do not use this as a reason to reset repository state.

## Commit/PR discipline

- Work is on `phase-4`.
- Stage only files authored/verified for the current change; the worktree may contain user-owned changes and local DB files.
- Do not commit `.env`, private keys, local test databases, OAuth data, cloud tokens, GitHub tokens, or secrets.
- Before a PR, run the focused control-plane tests and Terraform formatting/validation above, then record exactly what was tested in the PR summary.
- Treat `docs/phases/PHASE-4-mesh.md` as the acceptance authority. Update it and add a Phase 4 checkpoint only after the real backup/restore drill passes.

## Minimal opening prompt for the next Codex session

> Read `docs/HANDOFF.md`, then scan the repository and current git status. We are on `phase-4`, implementing the GKE production runtime. Do not discard the dirty worktree. First check Cloud Build `a5231ca8-b71b-4466-b7f9-c2221ce36c27`, verify GKE state read-only, run the focused backup-runtime tests, then continue the Phase 4 acceptance gates in `docs/phases/PHASE-4-mesh.md`.
