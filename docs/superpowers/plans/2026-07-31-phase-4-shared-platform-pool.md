# Phase 4 Shared Platform Pool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy initial GKE customer releases on the existing tainted `platform` node pool without creating the quota-blocked `workloads` pool.

**Architecture:** GKE remains two regional e2-standard-2 pools within the current 12-vCPU project-wide quota. The `system` pool stays untainted for GKE add-ons; every Rudder-generated customer Pod is forced onto the `platform` pool via an enforced selector and matching `NoSchedule` toleration. Runtime settings select this behavior only for GKE, while Kind retains its unrestricted local scheduling.

**Tech Stack:** Python 3.12, FastAPI settings, `kubernetes-asyncio`, pytest, Terraform, GKE Standard.

---

## File map

- Modify: `control-plane/rudder_cp/config.py` — expose and validate the selected GKE customer-workload pool.
- Modify: `control-plane/rudder_cp/runtime/targets.py` — map target-specific pool settings into the runtime.
- Modify: `control-plane/rudder_cp/runtime/kubernetes.py` — add enforced platform placement/toleration data to generated Deployments, StatefulSets, Jobs, CronJobs, and CNPG cluster manifests.
- Modify: `control-plane/tests/test_gke_target.py` — prove only GKE receives platform placement.
- Modify: `control-plane/tests/test_kubernetes_runtime.py` — prove caller-provided placement cannot escape the platform pool and every rendered Pod template tolerates the taint.
- Modify: `control-plane/tests/test_gke_node_pool_scheduling_contract.py` — prove Terraform leaves the workloads pool disabled and runtime enforces the shared pool.
- Modify: `infra/kubernetes/platform/control-plane.yaml`, `.env.example`, and `docs/phases/PHASE-4-gke-production-runtime.md` — production contract and migration documentation.

### Task 1: Add an explicit, target-safe shared-pool setting ✅

**Files:**
- Modify: `control-plane/rudder_cp/config.py`
- Modify: `control-plane/rudder_cp/runtime/targets.py`
- Test: `control-plane/tests/test_gke_target.py`

- [x] **Step 1: Write the failing target tests.**

```python
def test_gke_target_maps_the_required_platform_workload_pool() -> None:
    settings = Settings(
        runtime="kubernetes",
        kubernetes_target="gke",
        kubernetes_public_domain="rudder.invytt.com",
        base_domain="rudder.invytt.com",
        kubernetes_certificate_issuer="rudder-letsencrypt-prod",
        registry="asia-south1-docker.pkg.dev/invytt-2483d/rudder",
    )
    assert runtime_settings_from(settings).workload_node_selector == {
        "rudder.pool": "platform"
    }


def test_kind_target_does_not_force_gke_platform_placement() -> None:
    assert runtime_settings_from(Settings()).workload_node_selector == {}
```

- [x] **Step 2: Run the focused tests.**

Run: `cd control-plane && uv run pytest tests/test_gke_target.py -q`
Expected: FAIL because `workload_node_selector` does not exist.

- [x] **Step 3: Add the setting and mapping.**

```python
# Settings
kubernetes_workload_pool: str = "platform"

# GKE validation
if self.kubernetes_workload_pool != "platform":
    raise ValueError(
        "The current 12-vCPU GKE topology requires "
        "RUDDER_KUBERNETES_WORKLOAD_POOL=platform."
    )

# runtime_settings_from
workload_node_selector=(
    {"rudder.pool": settings.kubernetes_workload_pool}
    if settings.kubernetes_target == "gke"
    else {}
),
workload_tolerations=(
    (
        {
            "key": "rudder.pool",
            "operator": "Equal",
            "value": "platform",
            "effect": "NoSchedule",
        },
    )
    if settings.kubernetes_target == "gke"
    else ()
),
```

Add matching `RuntimeSettings` fields with safe empty defaults.

- [x] **Step 4: Run the focused tests.**

Run: `cd control-plane && uv run pytest tests/test_gke_target.py -q`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add control-plane/rudder_cp/config.py control-plane/rudder_cp/runtime/targets.py control-plane/tests/test_gke_target.py
git commit -m "feat: target GKE customer workloads to shared platform pool"
```

### Task 2: Enforce platform placement in every customer workload ✅

**Files:**
- Modify: `control-plane/rudder_cp/runtime/kubernetes.py`
- Test: `control-plane/tests/test_kubernetes_runtime.py`

- [x] **Step 1: Write failing placement tests.**

Add a release that requests `{"rudder.pool": "system"}`; configure its `RuntimeSettings` with the approved platform selector/toleration; assert the applied `WorkloadSpec` instead contains:

```python
assert workload.node_selector == {"rudder.pool": "platform"}
assert workload.tolerations == (
    {
        "key": "rudder.pool",
        "operator": "Equal",
        "value": "platform",
        "effect": "NoSchedule",
    },
)
```

Add an `AsyncKubernetesApi.apply_workload` test that captures the Pod template and asserts a Kubernetes `V1Toleration` with those four exact fields.

- [x] **Step 2: Run the focused tests.**

Run: `cd control-plane && uv run pytest tests/test_kubernetes_runtime.py -q`
Expected: FAIL because `WorkloadSpec` has no tolerations and caller placement is still used.

- [x] **Step 3: Implement non-bypassable placement.**

Add this field to `WorkloadSpec`:

```python
tolerations: tuple[Mapping[str, str], ...] = ()
```

When `KubernetesRuntime.apply` creates a workload, merge user placement first and runtime placement last:

```python
node_selector = {
    **dict(operation_config["node_selector"]),
    **dict(self.settings.workload_node_selector),
}
tolerations = self.settings.workload_tolerations
```

Pass both fields through both `WorkloadSpec` constructions. In
`AsyncKubernetesApi.apply_workload`, render:

```python
tolerations=[
    client.V1Toleration(**dict(item)) for item in spec.tolerations
] or None
```

Apply the same selector/toleration to CloudNativePG managed Pods, CronJob templates, and one-off Job templates. Do not alter the platform control-plane manifest, which already has explicit placement.

- [x] **Step 4: Run the focused tests.**

Run: `cd control-plane && uv run pytest tests/test_kubernetes_runtime.py -q`
Expected: PASS, including existing Kind behavior.

- [ ] **Step 5: Commit.**

```bash
git add control-plane/rudder_cp/runtime/kubernetes.py control-plane/tests/test_kubernetes_runtime.py
git commit -m "feat: enforce shared platform placement for GKE releases"
```

### Task 3: Preserve the 12-vCPU topology contract ✅

**Files:**
- Modify: `infra/kubernetes/platform/control-plane.yaml`
- Modify: `control-plane/tests/test_gke_node_pool_scheduling_contract.py`
- Modify: `.env.example`
- Modify: `docs/phases/PHASE-4-gke-production-runtime.md`

- [x] **Step 1: Write failing contract assertions.**

```python
assert "name: RUDDER_KUBERNETES_WORKLOAD_POOL" in control_plane
assert "value: platform" in control_plane
assert "enable_workloads_pool = false" in production_tfvars
assert "workload_node_selector" in runtime_source
```

- [x] **Step 2: Run the contract test.**

Run: `cd control-plane && uv run pytest tests/test_gke_node_pool_scheduling_contract.py -q`
Expected: FAIL for the absent workload-pool environment variable.

- [x] **Step 3: Update the production contract.**

Add this environment variable to the platform control-plane Deployment:

```yaml
- name: RUDDER_KUBERNETES_WORKLOAD_POOL
  value: platform
```

Document that this setting is mandatory while `CPUS_ALL_REGIONS` remains 12. The only supported migration is: increase aggregate quota, create Terraform's `workloads` pool, then switch the reviewed runtime setting from `platform` to `workloads`.

- [x] **Step 4: Run configuration and Python validation.**

```bash
cd control-plane && uv run pytest tests/test_gke_node_pool_scheduling_contract.py tests/test_gke_target.py tests/test_kubernetes_runtime.py -q
cd control-plane && uv run pytest -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit.**

```bash
git add infra/kubernetes/platform/control-plane.yaml control-plane/tests/test_gke_node_pool_scheduling_contract.py .env.example docs/phases/PHASE-4-gke-production-runtime.md
git commit -m "docs: record shared GKE platform pool topology"
```

### Task 4: Verify against live GKE without adding quota-bound infrastructure ✅

**Files:** verify only.

- [x] **Step 1: Confirm the current quota and pools.**

```bash
gcloud compute project-info describe --project=invytt-2483d --format=json | jq '.quotas[] | select(.metric == "CPUS_ALL_REGIONS")'
gcloud container clusters describe rudder-gke --project=invytt-2483d --region=asia-south1 --format='value(nodePools.name)'
```

Expected: `CPUS_ALL_REGIONS = 12/12`; only `system` and `platform` pools exist.

- [x] **Step 2: Check the Terraform plan.**

```bash
terraform -chdir=infra/gcp/terraform plan -var-file=envs/production.tfvars
```

Expected: no attempt to create `google_container_node_pool.workloads` and no destroy/replacement of either existing pool.

- [ ] **Step 3: Bootstrap only after runtime-secret and DNS prerequisites are satisfied.**

```bash
RUDDER_CONTROL_PLANE_IMAGE='asia-south1-docker.pkg.dev/invytt-2483d/rudder/control-plane@sha256:<digest>' \
RUDDER_CONTROL_PLANE_HOST='api.rudder.invytt.com' \
RUDDER_KUBERNETES_PUBLIC_DOMAIN='rudder.invytt.com' \
RUDDER_KUBERNETES_WORKLOAD_POOL='platform' \
infra/gcp/scripts/bootstrap-platform.sh
```

Expected: control-plane and customer workload Pods schedule on `rudder.pool=platform`; no workload pool is created.

- [ ] **Step 4: Verify placement after a disposable deployment.**

```bash
kubectl get pods -A -l app.kubernetes.io/managed-by=rudder -o wide
kubectl get nodes -L rudder.pool
```

Expected: all customer release Pods run on a `platform` node; no customer release Pod runs on a `system` node.
