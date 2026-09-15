# Kind metrics-server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make local Kind deployments expose real Kubernetes CPU and memory telemetry to Rudder's existing Analytics charts.

**Architecture:** The existing control-plane collector reads the Kubernetes `metrics.k8s.io` API and persists samples at ten-second resolution. The missing dependency is Kind platform bootstrap: it must install a pinned metrics-server manifest and wait for both its Deployment and aggregated API service before announcing readiness.

**Tech Stack:** Kind, kubectl, upstream metrics-server v0.7.2 manifest, pytest static bootstrap contract.

---

### Task 1: Lock the Kind platform contract

**Files:**
- Modify: `control-plane/tests/test_kind_control_plane_contract.py`

- [ ] **Step 1: Write the failing test**

```python
def test_kind_bootstrap_installs_and_waits_for_metrics_server() -> None:
    root = Path(__file__).resolve().parents[2]
    bootstrap = (root / "infra/kind/bootstrap.sh").read_text()

    assert "metrics-server/releases/download/v0.7.2/components.yaml" in bootstrap
    assert "deployment/metrics-server" in bootstrap
    assert "v1beta1.metrics.k8s.io" in bootstrap
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd control-plane && uv run pytest -q tests/test_kind_control_plane_contract.py -k metrics_server`

Expected: FAIL because Kind bootstrap does not install metrics-server.

- [ ] **Step 3: Write minimal implementation**

Add an idempotent metrics-server v0.7.2 apply to `infra/kind/bootstrap.sh`. Add the Kind-required `--kubelet-insecure-tls` argument with a targeted patch, wait for its Deployment to be Available, then wait until `v1beta1.metrics.k8s.io` is available.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd control-plane && uv run pytest -q tests/test_kind_control_plane_contract.py -k metrics_server`

Expected: PASS.

### Task 2: Reconcile local platform and prove the data path

**Files:**
- Modify: `infra/kind/README.md`

- [ ] **Step 1: Document the local capability**

Add one sentence that `make kind-up` installs metrics-server so Analytics uses real pod CPU/memory samples after a workload is healthy.

- [ ] **Step 2: Reconcile and verify the live platform**

Run: `make kind-up`

Run: `kubectl get apiservice v1beta1.metrics.k8s.io` and `kubectl top pods -A`

Expected: Available APIService and real pod usage output.

- [ ] **Step 3: Verify Rudder analytics persistence**

Wait one worker interval, then call the authenticated service metrics route through the UI or inspect the control-plane database.

Expected: non-empty ten-second-resolution samples and charts rendered by `analytics.tsx`.
