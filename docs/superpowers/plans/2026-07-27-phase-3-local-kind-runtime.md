# Phase 3 Local kind Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy a Rudder imported Compose topology into an isolated local `kind` namespace, surface Kubernetes lifecycle state in the existing deployment UI, and prove readiness-gated rollback safety end to end.

**Architecture:** A Kubernetes adapter sits behind the existing deployment pipeline. GitHub import and BuildKit continue to produce immutable images; the adapter maps the reviewed Compose graph to one namespace per Rudder environment, with Kubernetes resources labelled by project, environment, deployment, and service. Local `kind` is a disposable acceptance target, while GKE uses the same adapter later.

**Tech Stack:** Python 3.12, FastAPI, SQLModel, Kubernetes Python client, kind, Docker Registry v2, ingress-nginx, pytest, Docker Compose.

---

## File map

- Create `control-plane/rudder_cp/runtime/models.py`: runtime-neutral Compose release values.
- Create `control-plane/rudder_cp/runtime/kubernetes.py`: typed Kubernetes client adapter and resource translation.
- Create `control-plane/tests/test_kubernetes_runtime.py`: fake Kubernetes-client tests.
- Create `infra/kind/kind-config.yaml` and `infra/kind/bootstrap.sh`: local cluster/registry/ingress bootstrap.
- Create `scripts/verify-kind-e2e.sh`: disposable imported-release acceptance test.
- Modify `control-plane/rudder_cp/config.py`, `services/deploy.py`, and `services/worker.py`: runtime selection and lifecycle dispatch.
- Modify `control-plane/pyproject.toml`, `.env.example`, `docker-compose.dev.yml`, `Makefile`, `README.md`: dependency and local workflow.
- Modify `docs/phases/` and `docs/PRD.md`: Kubernetes becomes Phase 3, mesh becomes Phase 4, later phases are shifted.

### Task 1: Model an immutable Kubernetes release

**Files:**
- Create: `control-plane/rudder_cp/runtime/models.py`
- Test: `control-plane/tests/test_kubernetes_runtime.py`

- [ ] Write a failing test asserting a release is namespace scoped and resource names are DNS-safe and include the first eight deployment-ID characters.

```python
release = KubernetesRelease.from_compose(
    namespace="rudder-shop-production", release_id="aabbccdd", services=[...]
)
assert release.resource_name("web") == "web-aabbccdd"
```

- [ ] Run `cd control-plane && uv run pytest tests/test_kubernetes_runtime.py -k release_names -q`; expect an import failure.
- [ ] Implement frozen `ComposeService` and `KubernetesRelease` dataclasses. `ComposeService` carries name, image digest, port, command, environment, public, and stateful; `KubernetesRelease` owns namespace, release ID, service tuple, and `resource_name()`.
- [ ] Re-run the focused test; expect PASS.
- [ ] Commit: `git add control-plane/rudder_cp/runtime/models.py control-plane/tests/test_kubernetes_runtime.py && git commit -m "feat: model Kubernetes releases"`.

### Task 2: Translate a release into Kubernetes resources

**Files:**
- Create: `control-plane/rudder_cp/runtime/kubernetes.py`
- Modify: `control-plane/pyproject.toml`
- Test: `control-plane/tests/test_kubernetes_runtime.py`

- [ ] Write failing tests for a private Postgres service becoming a StatefulSet + PVC + ClusterIP Service and a public web service becoming a Deployment + Service + Ingress.

```python
await KubernetesRuntime(fake_kube, settings()).apply(release_with_postgres())
assert fake_kube.statefulsets["postgres-aabbccdd"].metadata.namespace == "rudder-shop-production"
assert fake_kube.services["postgres-aabbccdd"].spec.type == "ClusterIP"
assert fake_kube.pvcs["postgres-data-aabbccdd"].spec.resources.requests["storage"] == "1Gi"
```

- [ ] Run `cd control-plane && uv run pytest tests/test_kubernetes_runtime.py -k 'postgres or public_web' -q`; expect failure.
- [ ] Add `kubernetes-asyncio` and implement `KubernetesRuntime.apply()`: create/get namespace; apply default-deny NetworkPolicy, ResourceQuota, LimitRange; turn secret values into Kubernetes Secrets; create Deployment/StatefulSet, ClusterIP Service, PVC, and public-only Ingress; attach all `rudder.*` ownership labels.
- [ ] Do not use `kubectl` shell-outs; translate API exceptions into a runtime exception containing the object name and API reason.
- [ ] Run `cd control-plane && uv run ruff check rudder_cp/runtime tests/test_kubernetes_runtime.py && uv run pytest tests/test_kubernetes_runtime.py -q`; expect PASS.
- [ ] Commit: `git add control-plane/pyproject.toml control-plane/uv.lock control-plane/rudder_cp/runtime control-plane/tests/test_kubernetes_runtime.py && git commit -m "feat: add Kubernetes resource adapter"`.

### Task 3: Dispatch imported deployments through the selected runtime

**Files:**
- Modify: `control-plane/rudder_cp/config.py`
- Modify: `control-plane/rudder_cp/services/deploy.py`
- Modify: `control-plane/rudder_cp/services/worker.py`
- Test: `control-plane/tests/test_deploy.py`
- Test: `control-plane/tests/test_kubernetes_runtime.py`

- [ ] Write failing tests proving `RUDDER_RUNTIME=kubernetes` promotes only after every required workload is ready, and that a failed candidate leaves the previous live deployment and route unchanged.
- [ ] Add settings: `runtime` (`docker` or `kubernetes`), `kubeconfig_path`, `kubernetes_namespace_prefix`, `kubernetes_ingress_class`, and `kubernetes_local_domain`.
- [ ] Build the image through the existing builder, map the reviewed Compose graph into `KubernetesRelease`, create one `Instance` per Compose service using the pod UID, stream Kubernetes events to the existing build-log store, and promote only when the public service is `Available=True` plus all required private services are ready.
- [ ] On failure, delete only candidate-labelled Kubernetes resources, mark the candidate failed, and retain the prior live route. Restore must apply the recorded immutable image digest without invoking the builder.
- [ ] Run `cd control-plane && uv run pytest tests/test_deploy.py tests/test_kubernetes_runtime.py -q`; expect PASS.
- [ ] Commit: `git add control-plane/rudder_cp/config.py control-plane/rudder_cp/services/deploy.py control-plane/rudder_cp/services/worker.py control-plane/tests && git commit -m "feat: deploy imports through Kubernetes runtime"`.

### Task 4: Provide a reproducible local kind environment

**Files:**
- Create: `infra/kind/kind-config.yaml`
- Create: `infra/kind/bootstrap.sh`
- Create: `infra/kind/README.md`
- Create: `scripts/verify-kind-e2e.sh`
- Modify: `.env.example`, `docker-compose.dev.yml`, `Makefile`, `README.md`

- [ ] Implement idempotent bootstrap: create `rudder-kind` if absent, create/connect a `localhost:5001` registry, configure it for containerd, install ingress-nginx, and wait for its controller deployment.

```bash
kind get clusters | grep -qx rudder-kind || kind create cluster --name rudder-kind --config infra/kind/kind-config.yaml
kubectl --context kind-rudder-kind wait --namespace ingress-nginx --for=condition=Available deployment/ingress-nginx-controller --timeout=180s
```

- [ ] Add `make kind-up`, `make kind-down`, and `make verify-kind` targets. The verification script must create a disposable project/environment, deploy `web + worker + postgres + redis`, wait for ready labelled workloads, request the public web URL, assert private Postgres has no ingress, deploy a known broken revision, assert the old URL still succeeds, and delete the project namespace.
- [ ] Run `make kind-up && RUDDER_RUNTIME=kubernetes make verify-kind`; expect `kind end-to-end verification passed` and no remaining test namespace.
- [ ] Commit: `git add infra/kind scripts/verify-kind-e2e.sh .env.example docker-compose.dev.yml Makefile README.md && git commit -m "ops: add local kind acceptance environment"`.

### Task 5: Rename the phase roadmap and verify Step 1

**Files:**
- Create: `docs/phases/PHASE-3-kubernetes-runtime.md`
- Rename: `PHASE-3-mesh.md` → `PHASE-4-mesh.md`
- Rename: `PHASE-4-environments.md` → `PHASE-5-environments.md`
- Rename: `PHASE-5-operations.md` → `PHASE-6-operations.md`
- Rename: `PHASE-5.5-frontends.md` → `PHASE-6.5-frontends.md`
- Rename: `PHASE-6-advisor.md` → `PHASE-7-advisor.md`
- Modify: `docs/phases/README.md`, `docs/PRD.md`, `README.md`

- [ ] Replace the Phase 2.5 Kubernetes document with Phase 3's local-kind-first, GKE-Standard-second contract. Preserve the current mesh content as Phase 4 and update all later numbers and links.
- [ ] Verify no stale references remain: `rg -n 'PHASE-2\.5|Phase 2\.5|PHASE-3-mesh|Phase 3 — WireGuard' README.md docs`.
- [ ] Run all checks:

```bash
cd control-plane && uv run ruff check rudder_cp tests && uv run pytest tests -q
cd ../agent && uv run ruff check rudder_agent tests && uv run pytest tests -q
cd ../web && npm run typecheck && npm run build
cd .. && make kind-up && RUDDER_RUNTIME=kubernetes make verify-kind
```

- [ ] Commit and push: `git add docs README.md && git commit -m "docs: make Kubernetes the Phase 3 runtime" && git push -u origin phase-3`.
