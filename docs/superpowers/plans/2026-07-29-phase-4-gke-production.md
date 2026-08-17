# Phase 4 GKE Production Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Provision a repeatable GKE Standard landing zone and run the existing Rudder Kubernetes deployment workflow against it, with private workload networking, immutable Artifact Registry images, durable in-cluster PostgreSQL, and a verified public HTTPS application route.

**Architecture:** Terraform owns the GCP foundation only: a dedicated VPC, a regional private-node GKE Standard cluster, Artifact Registry, backup bucket, service accounts, and IAM. Rudder remains attach-mode: its control plane runs in `rudder-system`, uses Kubernetes in-cluster credentials and namespace-scoped RBAC, and reconciles a release into one labelled namespace per environment. ingress-nginx and cert-manager provide the portable edge; CloudNativePG owns Postgres while Redis remains a private StatefulSet.

**Tech Stack:** Terraform, Google Cloud (GKE Standard, Artifact Registry, Cloud Storage, IAM, Cloud DNS), Kubernetes, Helm, ingress-nginx, cert-manager, External Secrets Operator, CloudNativePG, Python/FastAPI, `kubernetes-asyncio`, pytest, Docker BuildKit.

---

## File map

- Create: `infra/gcp/terraform/{versions,providers,variables,network,cluster,registry,storage,identity,outputs}.tf` — reviewed GKE foundation.
- Create: `infra/gcp/terraform/envs/production.tfvars.example` — non-secret production input contract.
- Create: `infra/gcp/scripts/{bootstrap-platform,configure-kubectl,verify-gke}.sh` — explicit post-Terraform platform installation and acceptance checks.
- Create: `infra/kubernetes/platform/{namespace,rbac,control-plane,ingress,cert-manager,external-secrets,cloudnativepg}.yaml` — portable cluster add-ons and Rudder system workloads.
- Create: `control-plane/rudder_cp/runtime/targets.py` — runtime target selection and safe Kubernetes auth loading.
- Modify: `control-plane/rudder_cp/config.py` — explicit `kind`, `gke`, `kubeconfig`, and `in_cluster` configuration.
- Modify: `control-plane/rudder_cp/runtime/kubernetes.py` — GKE-safe namespace guardrails, in-cluster auth support, image registry/digest validation, and durable state semantics.
- Modify: `control-plane/rudder_cp/services/deploy.py` — record target, namespace, manifest revision, and immutable Artifact Registry digest in deployment progress.
- Modify: `control-plane/rudder_cp/services/rollbacks.py` — restore a recorded digest/manifest without building from the current branch.
- Modify: `control-plane/rudder_cp/models/{deployment,service}.py` and `control-plane/rudder_cp/schemas/*` — persistent target and workload state only if the existing record cannot represent it.
- Create: `control-plane/tests/test_gke_target.py` and modify `control-plane/tests/test_kubernetes_runtime.py`, `control-plane/tests/test_deploy.py`, `control-plane/tests/test_rollbacks.py` — focused unit/integration coverage.
- Modify: `.env.example`, `docker-compose.dev.yml`, `README.md`, `docs/GCP-Infrastructure.md`, and `docs/phases/PHASE-4-gke-production-runtime.md` — documented operator workflow and GKE acceptance evidence.

## Task 1: Add a repeatable GKE foundation in Terraform

**Files:**
- Create: `infra/gcp/terraform/versions.tf`
- Create: `infra/gcp/terraform/providers.tf`
- Create: `infra/gcp/terraform/variables.tf`
- Create: `infra/gcp/terraform/network.tf`
- Create: `infra/gcp/terraform/cluster.tf`
- Create: `infra/gcp/terraform/registry.tf`
- Create: `infra/gcp/terraform/storage.tf`
- Create: `infra/gcp/terraform/identity.tf`
- Create: `infra/gcp/terraform/outputs.tf`
- Create: `infra/gcp/terraform/envs/production.tfvars.example`

- [ ] **Step 1: Write a Terraform validation contract before creating resources.**

```hcl
# infra/gcp/terraform/variables.tf
variable "project_id" { type = string }
variable "region" { type = string  default = "asia-south1" }
variable "cluster_name" { type = string default = "rudder-gke" }
variable "network_name" { type = string default = "rudder-gke-vpc" }
variable "dns_zone_name" { type = string default = "rudder-subdomain" }
variable "dns_name" {
  type        = string
  default     = "rudder.invytt.com."
  validation {
    condition     = can(regex("^[a-z0-9.-]+\\.$", var.dns_name))
    error_message = "dns_name must be a fully-qualified DNS name ending in a dot."
  }
}
```

- [ ] **Step 2: Run `terraform fmt -check && terraform validate`; expect failure until the provider and resources exist.**
- [ ] **Step 3: Define pinned providers and the dedicated VPC with non-overlapping ranges.**

```hcl
# infra/gcp/terraform/network.tf
resource "google_compute_network" "rudder" {
  name                    = var.network_name
  auto_create_subnetworks = false
}

resource "google_compute_subnetwork" "gke" {
  name          = "${var.cluster_name}-subnet"
  region        = var.region
  network       = google_compute_network.rudder.id
  ip_cidr_range = "10.80.0.0/20"
  secondary_ip_range { range_name = "pods"     ip_cidr_range = "10.96.0.0/14" }
  secondary_ip_range { range_name = "services" ip_cidr_range = "10.112.0.0/20" }
  private_ip_google_access = true
}
```

- [ ] **Step 4: Define a regional, VPC-native, private-node GKE Standard cluster and three bounded node pools.**

```hcl
# infra/gcp/terraform/cluster.tf
resource "google_container_cluster" "rudder" {
  name     = var.cluster_name
  location = var.region
  network    = google_compute_network.rudder.id
  subnetwork = google_compute_subnetwork.gke.id
  networking_mode = "VPC_NATIVE"
  remove_default_node_pool = true
  initial_node_count       = 1
  workload_identity_config { workload_pool = "${var.project_id}.svc.id.goog" }
  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }
  private_cluster_config { enable_private_nodes = true }
  network_policy { enabled = true }
  release_channel { channel = "REGULAR" }
}
```

Create `system`, `platform`, and `workloads` pools with `min_node_count = 1`, `max_node_count = 3`, dedicated labels, autoscaling, and no public workload IPs. The actual machine types must be variables with `e2-standard-2` as development-acceptance default.

- [ ] **Step 5: Add a private Docker Artifact Registry repository, versioned backup bucket, and dedicated service accounts.**

```hcl
resource "google_artifact_registry_repository" "rudder" {
  location      = var.region
  repository_id = "rudder"
  format        = "DOCKER"
}

resource "google_storage_bucket" "backups" {
  name                        = "${var.project_id}-rudder-backups"
  location                    = var.region
  uniform_bucket_level_access = true
  versioning { enabled = true }
  lifecycle_rule { action { type = "Delete" } condition { age = 35 } }
}
```

Create `rudder-build`, `rudder-runtime`, and `rudder-backup` service accounts. Bind only `roles/artifactregistry.writer` to build, `roles/artifactregistry.reader` to runtime, and bucket-scoped storage permissions to backup. Do not grant project Owner, Editor, broad Storage Admin, or container Admin to any workload identity.

- [ ] **Step 6: Add outputs for the cluster endpoint, registry hostname, backup bucket, workload pool, and Cloud DNS nameservers.**

- [ ] **Step 7: Run `terraform fmt -recursive`, `terraform validate`, and `terraform plan -var-file=envs/production.tfvars`; expect a plan that creates no Compute Engine VM, Cloud SQL instance, public database, or public cache.**
- [ ] **Step 8: Commit the foundation.**

```bash
git add infra/gcp/terraform
git commit -m "infra: add GKE production foundation"
```

## Task 2: Install portable platform services and bind identity

**Files:**
- Create: `infra/gcp/scripts/bootstrap-platform.sh`
- Create: `infra/gcp/scripts/configure-kubectl.sh`
- Create: `infra/kubernetes/platform/namespace.yaml`
- Create: `infra/kubernetes/platform/rbac.yaml`
- Create: `infra/kubernetes/platform/control-plane.yaml`
- Create: `infra/kubernetes/platform/ingress-nginx.yaml`
- Create: `infra/kubernetes/platform/cert-manager.yaml`
- Create: `infra/kubernetes/platform/external-secrets.yaml`
- Create: `infra/kubernetes/platform/cloudnativepg.yaml`

- [ ] **Step 1: Write a shell test that fails unless the configured context is the expected GKE cluster.**

```bash
# infra/gcp/scripts/configure-kubectl.sh
set -euo pipefail
gcloud container clusters get-credentials "$RUDDER_GKE_CLUSTER" \
  --region "$RUDDER_GCP_REGION" --project "$RUDDER_GCP_PROJECT"
test "$(kubectl config current-context)" = "gke_${RUDDER_GCP_PROJECT}_${RUDDER_GCP_REGION}_${RUDDER_GKE_CLUSTER}"
```

- [ ] **Step 2: Run the script with an intentionally absent cluster name; expect `NOT_FOUND` and no Kubernetes object changes.**
- [ ] **Step 3: Create `rudder-system`, a dedicated control-plane ServiceAccount, and namespace-safe RBAC.**

```yaml
# infra/kubernetes/platform/rbac.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata: { name: rudder-environment-reconciler }
rules:
  - apiGroups: ["", "apps", "batch", "networking.k8s.io", "autoscaling"]
    resources: ["configmaps", "secrets", "services", "deployments", "statefulsets", "jobs", "cronjobs", "networkpolicies", "horizontalpodautoscalers"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: [""]
    resources: ["persistentvolumeclaims"]
    verbs: ["get", "list", "watch", "create", "update", "patch"]
```

Do not include PVC `delete`. Add a separate, disabled-by-default break-glass role for explicitly-authorised state destruction; Rudder’s normal control-plane ServiceAccount must never bind it.

- [ ] **Step 4: Install ingress-nginx, cert-manager, External Secrets Operator, and CloudNativePG with version-pinned Helm charts.**

```bash
helm upgrade --install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx --create-namespace --version "$INGRESS_NGINX_CHART_VERSION" \
  --set controller.service.externalTrafficPolicy=Local
helm upgrade --install cloudnative-pg cloudnative-pg/cloudnative-pg \
  --namespace cnpg-system --create-namespace --version "$CNPG_CHART_VERSION"
```

`bootstrap-platform.sh` must call `kubectl wait --for=condition=Available` for every controller Deployment and fail if any required Pod is not Ready.

- [ ] **Step 5: Bind the `rudder-control-plane` Kubernetes ServiceAccount to the dedicated Google runtime identity with Workload Identity.**

```bash
gcloud iam service-accounts add-iam-policy-binding "$RUNTIME_GSA" \
  --role roles/iam.workloadIdentityUser \
  --member "serviceAccount:${RUDDER_GCP_PROJECT}.svc.id.goog[rudder-system/rudder-control-plane]"
kubectl -n rudder-system annotate serviceaccount rudder-control-plane \
  iam.gke.io/gcp-service-account="$RUNTIME_GSA" --overwrite
```

- [ ] **Step 6: Run `kubectl auth can-i delete persistentvolumeclaims --as=system:serviceaccount:rudder-system:rudder-control-plane --all-namespaces`; expect `no`. Then run `kubectl get pods -A` and expect every platform controller Ready.**
- [ ] **Step 7: Commit the platform bootstrap.**

```bash
git add infra/gcp/scripts infra/kubernetes/platform
git commit -m "ops: bootstrap portable GKE platform services"
```

## Task 3: Make Rudder’s Kubernetes adapter explicitly target GKE

**Files:**
- Create: `control-plane/rudder_cp/runtime/targets.py`
- Modify: `control-plane/rudder_cp/config.py`
- Modify: `control-plane/rudder_cp/runtime/kubernetes.py`
- Modify: `control-plane/rudder_cp/services/deploy.py`
- Modify: `control-plane/rudder_cp/services/rollbacks.py`
- Create: `control-plane/tests/test_gke_target.py`
- Modify: `control-plane/tests/test_kubernetes_runtime.py`
- Modify: `control-plane/tests/test_deploy.py`
- Modify: `control-plane/tests/test_rollbacks.py`

- [ ] **Step 1: Write failing tests for target selection and non-destructive rollback.**

```python
async def test_gke_target_loads_in_cluster_config(monkeypatch):
    settings = Settings(runtime="kubernetes", kubernetes_target="gke")
    await load_kubernetes_client(settings)
    assert in_cluster_loader_called

async def test_restore_uses_recorded_digest_without_builder(...):
    await restore(previous_live_deployment.id)
    builder.build.assert_not_called()
    runtime.apply.assert_awaited_once()
    assert runtime.release.services[0].image == previous_live_deployment.image_digest
```

- [ ] **Step 2: Run `cd control-plane && uv run pytest tests/test_gke_target.py tests/test_rollbacks.py -q`; expect failure because `kubernetes_target` and the loader do not exist.**
- [ ] **Step 3: Implement typed target configuration and a single auth loader.**

```python
# control-plane/rudder_cp/runtime/targets.py
async def load_kubernetes_client(settings: Settings) -> AsyncKubernetesApi:
    runtime_settings = RuntimeSettings(
        local_domain=settings.kubernetes_public_domain,
        ingress_class=settings.kubernetes_ingress_class,
        readiness_timeout_seconds=settings.kubernetes_readiness_timeout_seconds,
        backup_s3_endpoint=settings.kubernetes_backup_s3_endpoint,
        backup_s3_bucket=settings.kubernetes_backup_s3_bucket,
        backup_s3_access_key=settings.kubernetes_backup_s3_access_key,
        backup_s3_secret_key=settings.kubernetes_backup_s3_secret_key,
        backup_s3_region=settings.kubernetes_backup_s3_region,
    )
    if settings.kubernetes_target == "gke":
        return await AsyncKubernetesApi.from_in_cluster(runtime_settings)
    return await AsyncKubernetesApi.from_kubeconfig(runtime_settings, kubeconfig_path=settings.kubernetes_kubeconfig)
```

`Settings` must accept only `kind` and `gke` for `kubernetes_target`; `gke` requires a non-`localhost` `kubernetes_public_domain`, `RUDDER_RUNTIME=kubernetes`, and no local registry address. Keep `kind` compatible with the existing `make kind-*` commands.

- [ ] **Step 4: Extend `AsyncKubernetesApi` with `from_in_cluster()` using `config.load_incluster_config()`, and make release logs state target, namespace, registry digest, and manifest revision.**
- [ ] **Step 5: Render GKE Ingresses only for `public=True` services and use `spec.ingressClassName = "nginx"`; render all databases, caches, queues, workers, observability services as ClusterIP.**
- [ ] **Step 6: Change CloudNativePG rendering from the Kind-only test path to a production-safe Cluster resource.**

```python
assert resource["spec"]["instances"] >= 2
assert resource["spec"]["storage"]["size"] == "10Gi"
assert resource["spec"]["backup"]["barmanObjectStore"]["destinationPath"].startswith("s3://")
```

The corresponding credentials must come from an ExternalSecret-created Kubernetes Secret; never put GCS HMAC credentials in the database model, build log, or deployment variables.

- [ ] **Step 7: Run `cd control-plane && uv run ruff check rudder_cp/runtime rudder_cp/services tests/test_gke_target.py tests/test_kubernetes_runtime.py && uv run pytest tests/test_gke_target.py tests/test_kubernetes_runtime.py tests/test_deploy.py tests/test_rollbacks.py -q`; expect PASS.**
- [ ] **Step 8: Commit the target-aware runtime.**

```bash
git add control-plane/rudder_cp control-plane/tests
git commit -m "feat: add GKE Kubernetes runtime target"
```

## Task 4: Run the control plane inside GKE and publish immutable images

**Files:**
- Modify: `control-plane/Dockerfile`
- Modify: `docker-compose.dev.yml`
- Create: `infra/kubernetes/platform/control-plane.yaml`
- Create: `infra/gcp/scripts/publish-control-plane.sh`
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Write an image-reference test that rejects mutable tags for GKE deployments.**

```python
def test_gke_release_requires_digest_reference():
    with pytest.raises(ValueError, match="immutable digest"):
        validate_gke_image("asia-south1-docker.pkg.dev/invytt-2483d/rudder/api:latest")
```

- [ ] **Step 2: Run the focused test; expect failure before validation is implemented.**
- [ ] **Step 3: Add the publish script that performs one authenticated BuildKit build, pushes to Artifact Registry, and emits the immutable digest.**

```bash
IMAGE="${RUDDER_REGISTRY}/${RUDDER_CONTROL_PLANE_IMAGE}:${GIT_SHA}"
docker buildx build --push --platform linux/amd64 --tag "$IMAGE" control-plane
DIGEST="$(gcloud artifacts docker images describe "$IMAGE" --format='value(image_summary.digest)')"
printf '%s@%s\n' "$IMAGE" "$DIGEST"
```

- [ ] **Step 4: Create the `rudder-system` Deployment using the returned digest, the `rudder-control-plane` ServiceAccount, `RUDDER_KUBERNETES_TARGET=gke`, and only Secret references for production values.**

```yaml
env:
  - name: RUDDER_RUNTIME
    value: kubernetes
  - name: RUDDER_KUBERNETES_TARGET
    value: gke
  - name: RUDDER_REGISTRY
    value: asia-south1-docker.pkg.dev/invytt-2483d/rudder
```

- [ ] **Step 5: Apply the workload and wait for readiness: `kubectl -n rudder-system rollout status deployment/rudder-control-plane --timeout=180s`; expect `successfully rolled out`.**
- [ ] **Step 6: Ensure the control-plane ServiceAccount cannot list or modify unrelated namespaces, and can reconcile a labelled `rudder-*` namespace.**
- [ ] **Step 7: Commit the GKE control-plane delivery artifact.**

```bash
git add control-plane/Dockerfile docker-compose.dev.yml infra/kubernetes/platform infra/gcp/scripts .env.example README.md
git commit -m "ops: run Rudder control plane on GKE"
```

## Task 5: Prove public HTTPS, isolation, rollback, and data recovery

**Files:**
- Create: `infra/gcp/scripts/verify-gke.sh`
- Create: `control-plane/scripts/verify_gke.py`
- Modify: `control-plane/tests/test_kubernetes_runtime.py`
- Modify: `docs/GCP-Infrastructure.md`
- Modify: `docs/phases/PHASE-4-gke-production-runtime.md`

- [ ] **Step 1: Write an acceptance script with explicit pass/fail assertions.**

```bash
kubectl get namespace "$RUDDER_NAMESPACE"
kubectl -n "$RUDDER_NAMESPACE" rollout status deployment/app --timeout=180s
kubectl -n "$RUDDER_NAMESPACE" rollout status statefulset/redis --timeout=180s
kubectl -n "$RUDDER_NAMESPACE" get cluster.postgresql.cnpg.io/postgres
curl --fail --resolve "$RUDDER_PUBLIC_HOST:443:$RUDDER_INGRESS_IP" "https://$RUDDER_PUBLIC_HOST/health"
```

- [ ] **Step 2: Deploy a disposable GitHub-imported `app + worker + postgres + redis` release. Record its resolved image digest, namespace, public hostname, pod readiness, and database backup ID.**
- [ ] **Step 3: Assert that the app is public but Postgres, Redis, and worker have only ClusterIP Services.**

```bash
test "$(kubectl -n "$RUDDER_NAMESPACE" get svc postgres -o jsonpath='{.spec.type}')" = "ClusterIP"
test "$(kubectl -n "$RUDDER_NAMESPACE" get svc redis -o jsonpath='{.spec.type}')" = "ClusterIP"
! kubectl -n "$RUDDER_NAMESPACE" get ingress postgres
! kubectl -n "$RUDDER_NAMESPACE" get ingress redis
```

- [ ] **Step 4: Test private isolation with a disposable Pod in another Rudder namespace; DNS may resolve but the TCP connection to Postgres must fail. Then verify the app namespace connection succeeds.**
- [ ] **Step 5: Deploy a deliberately broken image digest. Assert candidate readiness fails, the previously live public route continues returning HTTP 200, and deployment history marks only the candidate failed.**
- [ ] **Step 6: Restore the earlier deployment from the UI/API. Assert no builder invocation appears in logs, the active manifest uses the earlier digest, and the public route remains HTTP 200 throughout.**
- [ ] **Step 7: Execute one CNPG backup and restore drill into a disposable namespace. Verify a sentinel row exists after restore, then delete only the disposable restored namespace.**
- [ ] **Step 8: Run all quality gates.**

```bash
cd control-plane && uv run ruff check rudder_cp tests && uv run pytest tests -q
cd ../agent && uv run ruff check rudder_agent tests && uv run pytest tests -q
cd ../web && npm run typecheck && npm run build
cd .. && bash infra/gcp/scripts/verify-gke.sh
```

- [ ] **Step 9: Record exact GKE cluster name, region, namespace, image digest, public host, tests, backup/restore evidence, known cost, and GoDaddy delegation requirement in the two Phase 4 handoff documents. Never record keys, tokens, kubeconfigs, or database secrets.**
- [ ] **Step 10: Commit and open the Phase 4 pull request.**

```bash
git add docs/GCP-Infrastructure.md docs/phases/PHASE-4-gke-production-runtime.md infra/gcp/scripts control-plane/scripts control-plane/tests
git commit -m "docs: verify Phase 4 GKE acceptance"
git push -u origin phase-4
gh pr create --base main --head phase-4 --title "Phase 4: GKE production runtime" --body-file docs/phases/PHASE-4-gke-production-runtime.md
```

## Production operator actions outside this repository

1. Configure a versioned remote Terraform state bucket before the first `terraform apply`; do not apply shared-cluster infrastructure from local Terraform state.
2. Run `terraform apply` only after reviewing its plan for `invytt-2483d` and `asia-south1`.
3. After Terraform prints Cloud DNS nameservers, add those NS records for `rudder.invytt.com` in GoDaddy and wait for delegation to resolve.
4. Store GitHub, database, S3/HMAC, and application secrets in Secret Manager; do not put them in `.env`, Terraform variables, commits, or build logs.
5. Point a production GitHub App webhook at the public Rudder control-plane hostname only after TLS is live.

## Self-review

- Spec coverage: Tasks 1–2 implement the GKE landing zone, private networking, identity, ingress, certs, and CNPG; Tasks 3–4 bind the existing runtime/control plane to it; Task 5 proves deployment, private isolation, rollback, public health, and backup recovery.
- Placeholder scan: no deferred implementation markers or unspecified implementation steps are used; all external operator steps are intentionally segregated from repository code.
- Type consistency: `Settings.kubernetes_target`, `load_kubernetes_client()`, `AsyncKubernetesApi.from_in_cluster()`, immutable digest references, and `rudder-control-plane` are used consistently across all tasks.
