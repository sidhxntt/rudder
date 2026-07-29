# Kubernetes Operations Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement safe Kubernetes workload, data, job, scaling, rollout, placement, and observability controls end-to-end in Rudder.

**Architecture:** A typed operations configuration becomes durable desired state on a service. API operations validate capability and mutate this desired state or create an auditable operation record; the Kubernetes runtime translates the normalized state into Deployments, StatefulSets, HPAs, Jobs/CronJobs, PVCs, policies, and routes. The detail panel reads the same desired and observed state so its controls always correspond to actual Kubernetes resources.

**Tech Stack:** FastAPI, SQLModel/Alembic, Pydantic, Kubernetes async Python client, React/Next.js, TanStack Query, Vitest, pytest, Kind.

---

## File structure

- `control-plane/rudder_cp/models/operations.py`: durable operations and backup records.
- `control-plane/rudder_cp/schemas/operations.py`: typed request/response and validation rules.
- `control-plane/rudder_cp/services/operations.py`: capability checks, desired-state writes, operation lifecycle.
- `control-plane/rudder_cp/routers/operations.py`: service operation HTTP endpoints.
- `control-plane/rudder_cp/runtime/models.py`: normalized workload/data/job/autoscale/placement specs.
- `control-plane/rudder_cp/runtime/kubernetes.py`: Kubernetes resource translation and observed-state reads.
- `control-plane/rudder_cp/services/deploy.py`: include per-service operation intent in an immutable release.
- `control-plane/rudder_cp/services/monitor.py`: reconcile observed workload/job/replica/backup state.
- `control-plane/alembic/versions/*_add_service_operations.py`: database migration.
- `web/lib/{types,api,queries}.ts`: wire types and data hooks.
- `web/app/projects/[projectId]/environments/[environmentId]/operations.tsx`: operations UI.
- `web/app/projects/[projectId]/environments/[environmentId]/detail-panel.tsx`: Operations tab integration.
- `control-plane/tests/test_operations*.py`, `web/.../operations.test.tsx`, and `control-plane/scripts/verify_kind.py`: test coverage and E2E acceptance.

### Task 1: Persist typed operations intent

**Files:**
- Create: `control-plane/rudder_cp/models/operations.py`
- Create: `control-plane/rudder_cp/schemas/operations.py`
- Create: `control-plane/alembic/versions/<revision>_add_service_operations.py`
- Modify: `control-plane/rudder_cp/models/__init__.py`
- Test: `control-plane/tests/test_operations_schema.py`

- [ ] **Step 1: Write the failing schema tests**

```python
def test_workload_operations_reject_database_manual_scale():
    with pytest.raises(ValidationError, match="database primaries"):
        ScaleRequest(replicas=3, service_kind=ServiceKind.DATABASE)

def test_data_operations_reject_pvc_shrink():
    with pytest.raises(ValidationError, match="cannot shrink"):
        StorageResizeRequest(current_size_mb=1024, requested_size_mb=512)
```

- [ ] **Step 2: Run RED**

Run: `cd control-plane && uv run pytest tests/test_operations_schema.py -q`

Expected: import/validation failure because operation schemas do not exist.

- [ ] **Step 3: Implement records, migration, and models**

```python
class ServiceOperation(SQLModel, table=True):
    id: uuid.UUID = uuid_pk()
    service_id: uuid.UUID = Field(foreign_key="service.id", sa_type=sa.Uuid)
    kind: OperationKind = Field(sa_column=sa.Column(pg_enum(OperationKind, "operation_kind")))
    status: OperationStatus = Field(default=OperationStatus.PENDING)
    requested: dict[str, Any] = Field(sa_column=sa.Column(sa.JSON, nullable=False))
    observed: dict[str, Any] = Field(default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False))
```

Define Pydantic models for workload scale, resources, HPA, placement, rollout, backup/restore, read replica, PVC expansion, CronJob, one-off Job, and observability. Validate unsafe combinations before persistence.

- [ ] **Step 4: Run GREEN**

Run: `cd control-plane && uv run pytest tests/test_operations_schema.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add control-plane/rudder_cp/models control-plane/rudder_cp/schemas control-plane/alembic/versions control-plane/tests/test_operations_schema.py
git commit -m "feat: persist Kubernetes service operations"
```

### Task 2: Build operations API and idempotent desired-state writes

**Files:**
- Create: `control-plane/rudder_cp/services/operations.py`
- Create: `control-plane/rudder_cp/routers/operations.py`
- Modify: `control-plane/rudder_cp/main.py`
- Test: `control-plane/tests/test_operations_api.py`

- [ ] **Step 1: Write failing API tests**

```python
async def test_manual_scale_creates_one_pending_operation(client, app_service):
    response = await client.post(f"/services/{app_service.id}/operations/scale", json={"replicas": 3})
    assert response.status_code == 202
    assert response.json()["requested"] == {"replicas": 3}

async def test_read_replica_is_private_and_returns_read_url(client, postgres_service):
    response = await client.post(f"/services/{postgres_service.id}/operations/data/read-replicas", json={"replicas": 1})
    assert response.status_code == 202
    assert response.json()["requested"]["public"] is False
```

- [ ] **Step 2: Run RED**

Run: `cd control-plane && uv run pytest tests/test_operations_api.py -q`

Expected: 404 because the router does not exist.

- [ ] **Step 3: Implement router and service operations**

Implement `GET /services/{id}/operations` and distinct 202 endpoints for all operations declared in the design. Use stable request hashes for idempotency; set matching service operations intent; create one `ServiceOperation`; enqueue reconciliation. `rollback` calls the existing immutable-domain target operation and creates an audit record without invoking the image builder.

- [ ] **Step 4: Run GREEN**

Run: `cd control-plane && uv run pytest tests/test_operations_api.py -q`

Expected: PASS; duplicate request returns the existing operation.

- [ ] **Step 5: Commit**

```bash
git add control-plane/rudder_cp/services/operations.py control-plane/rudder_cp/routers/operations.py control-plane/rudder_cp/main.py control-plane/tests/test_operations_api.py
git commit -m "feat: expose Kubernetes operations API"
```

### Task 3: Translate workload scale, resources, health, placement and HPA

**Files:**
- Modify: `control-plane/rudder_cp/runtime/models.py`
- Modify: `control-plane/rudder_cp/runtime/kubernetes.py`
- Modify: `control-plane/rudder_cp/services/deploy.py`
- Test: `control-plane/tests/test_kubernetes_operations_runtime.py`

- [ ] **Step 1: Write failing runtime tests**

```python
async def test_runtime_applies_requested_replicas_resources_and_spread(api):
    spec = WorkloadSpec(..., replicas=3, cpu_request="500m", memory_limit="1Gi", topology_spread=True)
    await runtime.apply(release_with(spec), project_id="p", environment_id="e")
    assert api.deployments[spec.name].spec.replicas == 3
    assert api.deployments[spec.name].spec.template.spec.containers[0].resources.limits["memory"] == "1Gi"

async def test_runtime_creates_hpa_only_for_stateless_workloads(api):
    await runtime.apply(release_with_hpa(min_replicas=2, max_replicas=5), project_id="p", environment_id="e")
    assert api.hpas
```

- [ ] **Step 2: Run RED**

Run: `cd control-plane && uv run pytest tests/test_kubernetes_operations_runtime.py -q`

Expected: `WorkloadSpec` does not accept operations fields / fake API lacks HPA.

- [ ] **Step 3: Implement Kubernetes translation**

Extend `WorkloadSpec` with requested replicas/resources, `pod_affinity`, `topology_spread`, `node_selector`, and optional autoscale policy. Add the Autoscaling API client and replace-safe HPA resource. Include resource requests and limits in the Pod container. Make readiness require requested replicas, not merely one ready pod.

- [ ] **Step 4: Run GREEN**

Run: `cd control-plane && uv run pytest tests/test_kubernetes_operations_runtime.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add control-plane/rudder_cp/runtime control-plane/rudder_cp/services/deploy.py control-plane/tests/test_kubernetes_operations_runtime.py
git commit -m "feat: reconcile Kubernetes workload controls"
```

### Task 4: Add stateful data operations

**Files:**
- Modify: `control-plane/rudder_cp/runtime/models.py`
- Modify: `control-plane/rudder_cp/runtime/kubernetes.py`
- Modify: `control-plane/rudder_cp/services/operations.py`
- Test: `control-plane/tests/test_kubernetes_data_operations.py`

- [ ] **Step 1: Write failing data runtime tests**

```python
async def test_postgres_read_replica_is_private_statefulset_with_readonly_url(api):
    result = await runtime.apply(release_with_postgres_replica(), project_id="p", environment_id="e")
    assert api.statefulsets["postgres-read-..."].spec.replicas == 1
    assert "postgres-read" not in result.public_hosts

async def test_volume_expansion_replaces_pvc_request(api):
    await runtime.expand_volume(namespace="e", claim="data-postgres", size="5Gi")
    assert api.pvcs["data-postgres"].spec.resources.requests["storage"] == "5Gi"
```

- [ ] **Step 2: Run RED**

Run: `cd control-plane && uv run pytest tests/test_kubernetes_data_operations.py -q`

Expected: missing replica/volume operations.

- [ ] **Step 3: Implement data translation**

Support a `data_role` (`primary`, `read-replica`) and `storage_mb`. Create private read-replica StatefulSets for PostgreSQL/MySQL using replicated secret configuration and surface a read-only service variable. Expand PVCs only if requested size is greater. Implement backup and restore as bounded Jobs with operation records; pause primary writes before restore and mark completion only when the post-restore probe succeeds. Keep Redis/Mongo capability-gated.

- [ ] **Step 4: Run GREEN**

Run: `cd control-plane && uv run pytest tests/test_kubernetes_data_operations.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add control-plane/rudder_cp/runtime control-plane/rudder_cp/services/operations.py control-plane/tests/test_kubernetes_data_operations.py
git commit -m "feat: add managed data operations"
```

### Task 5: Add scheduled and one-off jobs

**Files:**
- Modify: `control-plane/rudder_cp/runtime/kubernetes.py`
- Modify: `control-plane/rudder_cp/services/operations.py`
- Test: `control-plane/tests/test_kubernetes_jobs.py`

- [ ] **Step 1: Write failing job tests**

```python
async def test_schedule_creates_private_cronjob_with_bounded_history(api):
    await operations.create_schedule(service.id, cron="0 * * * *", command=("python", "manage.py", "cleanup"))
    assert api.cronjobs[service.id].spec.successful_jobs_history_limit == 3

async def test_one_off_job_stores_operation_and_returns_logs_reference(client, service):
    response = await client.post(f"/services/{service.id}/operations/jobs/run", json={"command": ["python", "manage.py", "migrate"]})
    assert response.status_code == 202
```

- [ ] **Step 2: Run RED**

Run: `cd control-plane && uv run pytest tests/test_kubernetes_jobs.py -q`

Expected: endpoints/resource methods missing.

- [ ] **Step 3: Implement CronJob and Job resources**

Create/update CronJobs with active deadline, retry, concurrency and bounded history. Create manual Jobs with immutable operation labels, timeout and log reference. Use template/service command allowlists; reject arbitrary commands.

- [ ] **Step 4: Run GREEN**

Run: `cd control-plane && uv run pytest tests/test_kubernetes_jobs.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add control-plane/rudder_cp/runtime/kubernetes.py control-plane/rudder_cp/services/operations.py control-plane/tests/test_kubernetes_jobs.py
git commit -m "feat: add Kubernetes scheduled and manual jobs"
```

### Task 6: Add observed state, rollout status and immutable rollback

**Files:**
- Modify: `control-plane/rudder_cp/services/monitor.py`
- Modify: `control-plane/rudder_cp/services/operations.py`
- Modify: `control-plane/rudder_cp/runtime/kubernetes.py`
- Test: `control-plane/tests/test_operations_monitor.py`

- [ ] **Step 1: Write failing observation tests**

```python
async def test_monitor_marks_scale_operation_healthy_only_at_target_replicas(session, fake_cluster):
    await reconcile_operations(session, fake_cluster)
    assert operation.status == OperationStatus.HEALTHY

async def test_rollback_retargets_live_immutable_deployment_without_builder(session, monkeypatch):
    await rollback_operation(session, deployment.id)
    builder.assert_not_called()
```

- [ ] **Step 2: Run RED**

Run: `cd control-plane && uv run pytest tests/test_operations_monitor.py -q`

Expected: operation observer unavailable.

- [ ] **Step 3: Implement observed-state reconciler**

Read Deployment/StatefulSet ready replicas, HPA conditions, Jobs, CronJobs, PVC capacity, and Pod readiness. Persist compact observed state. Map operation to `pending`, `progressing`, `healthy`, `degraded`, or `failed`. Reuse existing domain targeting rollback primitive and do not create a deployment.

- [ ] **Step 4: Run GREEN**

Run: `cd control-plane && uv run pytest tests/test_operations_monitor.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add control-plane/rudder_cp/services/monitor.py control-plane/rudder_cp/services/operations.py control-plane/rudder_cp/runtime/kubernetes.py control-plane/tests/test_operations_monitor.py
git commit -m "feat: report Kubernetes operation health and rollback"
```

### Task 7: Build Operations UI and data hooks

**Files:**
- Modify: `web/lib/types.ts`
- Modify: `web/lib/api.ts`
- Modify: `web/lib/queries.ts`
- Create: `web/app/projects/[projectId]/environments/[environmentId]/operations.tsx`
- Modify: `web/app/projects/[projectId]/environments/[environmentId]/detail-panel.tsx`
- Test: `web/app/projects/[projectId]/environments/[environmentId]/operations.test.tsx`

- [ ] **Step 1: Write failing UI tests**

```tsx
it("submits a manual app scale and refreshes observed status", async () => {
  render(<Operations service={appService} />);
  await user.selectOptions(screen.getByLabelText("Replicas"), "3");
  await user.click(screen.getByRole("button", { name: "Apply scale" }));
  expect(fetch).toHaveBeenCalledWith(`/api/services/${appService.id}/operations/scale`, expect.anything());
});

it("hides read replicas for a Redis service", () => {
  render(<Operations service={redisService} />);
  expect(screen.queryByText("Read replicas")).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run RED**

Run: `cd web && npm test -- operations.test.tsx`

Expected: Operations component not found.

- [ ] **Step 3: Implement the operations tab**

Add typed operations query/mutations and a responsive Operations tab with Run, Release, Data, and Jobs & placement sections. Render only supported controls. Use explicit confirmation dialogs for restore, read-replica creation, and traffic changes. Show request status and observed Kubernetes status separately. Add an immutable rollback button labelled `Restore — no rebuild`.

- [ ] **Step 4: Run GREEN**

Run: `cd web && npm test -- operations.test.tsx`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add web/lib web/app/projects/[projectId]/environments/[environmentId]
git commit -m "feat: add Kubernetes operations controls UI"
```

### Task 8: Add environment observability controls

**Files:**
- Modify: `control-plane/rudder_cp/services/operations.py`
- Modify: `control-plane/rudder_cp/runtime/kubernetes.py`
- Create: `web/app/projects/[projectId]/environments/[environmentId]/observability-card.tsx`
- Modify: `web/app/projects/[projectId]/environments/[environmentId]/canvas.tsx`
- Test: `control-plane/tests/test_observability_operations.py`
- Test: `web/app/projects/[projectId]/environments/[environmentId]/observability-card.test.tsx`

- [ ] **Step 1: Write failing tests**

```python
async def test_enable_observability_applies_private_prometheus_and_grafana(session):
    operation = await operations.enable_observability(session, environment.id)
    assert operation.requested["addons"] == ["prometheus", "grafana"]
```

```tsx
it("shows enabled health and links only when Grafana is public", () => {
  render(<ObservabilityCard state={enabledState} />);
  expect(screen.getByText("Prometheus healthy")).toBeVisible();
});
```

- [ ] **Step 2: Run RED**

Run: `cd control-plane && uv run pytest tests/test_observability_operations.py -q && cd ../web && npm test -- observability-card.test.tsx`

Expected: missing operation/card.

- [ ] **Step 3: Implement add-on policy**

Provision namespaced Prometheus/Grafana from Rudder-owned images/templates; default both to private; add only requested public Grafana route; apply resource limits and collect observed health.

- [ ] **Step 4: Run GREEN**

Run: same command as Step 2.

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add control-plane/rudder_cp/services/operations.py control-plane/rudder_cp/runtime/kubernetes.py control-plane/tests/test_observability_operations.py web/app/projects/[projectId]/environments/[environmentId]
git commit -m "feat: add managed observability controls"
```

### Task 9: Complete acceptance, migration, and regression verification

**Files:**
- Modify: `control-plane/scripts/verify_kind.py`
- Modify: `docs/phases/PHASE-3-kubernetes-runtime.md`
- Test: `control-plane/tests/test_operations_api.py`
- Test: `web/app/projects/[projectId]/environments/[environmentId]/operations.test.tsx`

- [ ] **Step 1: Write Kind acceptance assertions before extending the verifier**

```python
assert await request_json("POST", f"/services/{web_id}/operations/scale", {"replicas": 2})
assert await wait_for_replicas(namespace, "app", 2)
assert await rollback_without_new_image(service_id=web_id)
assert await wait_for_private_postgres_read_replica(namespace)
assert await wait_for_cronjob(namespace, "maintenance")
```

- [ ] **Step 2: Run RED**

Run: `make verify-kind`

Expected: assertion failure because operations are not yet fully exercised.

- [ ] **Step 3: Implement acceptance flow and documentation**

Extend the verifier to import an isolated app/worker/Postgres/Redis project, then exercise app scale, resource change, HPA, CronJob, immutable restore, Postgres read replica, PVC expansion, failed candidate route preservation, and observability. Document local Kind limitations and equivalent GKE managed storage/ingress requirements.

- [ ] **Step 4: Verify complete suite**

Run:

```bash
cd control-plane && UV_CACHE_DIR=/tmp/rudder-uv-cache uv run pytest tests -q
cd ../web && npm test && npm run typecheck && npm run build
cd .. && make verify-kind
```

Expected: all tests pass and Kind verifies every user-visible operation.

- [ ] **Step 5: Commit**

```bash
git add control-plane/scripts/verify_kind.py docs/phases/PHASE-3-kubernetes-runtime.md control-plane/tests web
git commit -m "test: verify Kubernetes operations end to end"
```

