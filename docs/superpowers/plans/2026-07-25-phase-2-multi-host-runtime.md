# Phase 2 Multi-host Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a verified two-node GCP runtime that schedules stateless Rudder workloads to a specific healthy agent, accurately reports instances in the UI, and handles node loss without duplicating stateful data.

**Architecture:** The control plane selects and transactionally reserves a `Node`, then creates a node-bound `AgentClient` for that node's private address. Agents authenticate both directions with the shared secret and heartbeats provide authoritative observed state. Reconciliation uses the same agent API as deployment and reschedules only stateless instances after a node becomes unreachable.

**Tech Stack:** FastAPI, SQLModel/PostgreSQL, aiohttp, Docker/Compose, Next.js/React Query, GCP Compute Engine, Docker Compose, systemd.

---

### Task 1: Make agent addressing and authentication node-aware

**Files:**
- Modify: `control-plane/rudder_cp/services/agent_client.py`
- Modify: `control-plane/rudder_cp/config.py`
- Modify: `agent/rudder_agent/main.py`
- Test: `control-plane/tests/test_agent_client.py`
- Test: `agent/tests/test_app_auth.py`

- [ ] **Step 1: Write failing tests for the private node URL and agent secret.**

```python
client = AgentClient.for_node("10.42.0.4", settings)
assert client.base_url == "http://10.42.0.4:9000"
assert request.headers["X-Rudder-Agent-Secret"] == settings.agent_shared_secret
```

- [ ] **Step 2: Run the focused tests and confirm they fail.**

Run: `cd control-plane && uv run pytest tests/test_agent_client.py -q`

- [ ] **Step 3: Implement one node-bound `AgentClient` factory and shared-secret headers.**

```python
@classmethod
def for_node(cls, node: Node, settings: Settings) -> "AgentClient":
    return cls(f"http://{node.ip_address}:9000", shared_secret=settings.agent_shared_secret)
```

The agent middleware must reject unauthenticated control-plane commands while
leaving `/healthz`, registration, and heartbeat behavior explicit.

- [ ] **Step 4: Run focused tests and lint.**

Run: `cd control-plane && uv run pytest tests/test_agent_client.py -q && uv run ruff check rudder_cp/services/agent_client.py`

- [ ] **Step 5: Commit the focused change.**

```bash
git add control-plane/rudder_cp/services/agent_client.py control-plane/rudder_cp/config.py agent/rudder_agent/main.py control-plane/tests/test_agent_client.py agent/tests/test_app_auth.py
git commit -m "feat: address authenticated node agents"
```

### Task 2: Make placement atomic and execute against the selected node

**Files:**
- Modify: `control-plane/rudder_cp/services/scheduler.py`
- Modify: `control-plane/rudder_cp/services/deploy.py`
- Test: `control-plane/tests/test_scheduler.py`
- Test: `control-plane/tests/test_deploy.py`

- [ ] **Step 1: Add a failing test for row-locked selection returning a `Node`.**

```python
node = select_node_for_service(session, service)
assert node.id == eligible_node.id
```

- [ ] **Step 2: Add a failing deploy test proving the selected node's agent receives create/Compose commands.**

```python
assert agent_factory_calls == [eligible_node.id]
assert instance.node_id == eligible_node.id
```

- [ ] **Step 3: Lock candidates before capacity choice, reserve capacity and create the instance in one transaction, then invoke `AgentClient.for_node`.**

```python
locked = session.exec(select(Node).where(Node.id == node.id).with_for_update()).one()
locked.cpu_allocated += service.cpu_limit
session.add(Instance(deployment_id=deployment.id, node_id=locked.id, status=InstanceStatus.STARTING))
session.commit()
agent = agent_factory(locked, settings)
```

Release the reservation on startup/health-check failure. Compose child instances
must use the selected node too.

- [ ] **Step 4: Run all deployment and scheduler tests.**

Run: `cd control-plane && uv run pytest tests/test_scheduler.py tests/test_deploy.py -q`

- [ ] **Step 5: Commit the atomic placement change.**

```bash
git add control-plane/rudder_cp/services/scheduler.py control-plane/rudder_cp/services/deploy.py control-plane/tests/test_scheduler.py control-plane/tests/test_deploy.py
git commit -m "feat: schedule deployments on reserved nodes"
```

### Task 3: Reconcile actual state through the real agent API

**Files:**
- Modify: `control-plane/rudder_cp/services/reconciler.py`
- Modify: `control-plane/rudder_cp/services/nodes.py`
- Modify: `control-plane/rudder_cp/main.py`
- Test: `control-plane/tests/test_reconciler.py`

- [ ] **Step 1: Write failing tests for unreachable-node marking, idempotent repeated reconciliation, and orphan cleanup through port 9000.**

```python
await reconcile_state(session, agent_factory)
await reconcile_state(session, agent_factory)
assert agent.delete_calls == [orphan_id]
assert node.status == NodeStatus.UNREACHABLE
```

- [ ] **Step 2: Replace the incompatible `:8001/v1` client with the shared `AgentClient` methods.**

```python
agent = agent_factory(node, settings)
await agent.remove(instance.container_id, drain_seconds=0)
```

- [ ] **Step 3: Reschedule only stateless unreachable instances.**

```python
if service_has_persistent_volume(session, service.id):
    instance.status = InstanceStatus.DEGRADED
else:
    queue_replacement_deployment(session, instance)
```

The replacement must receive a new desired generation and stale observations
must not create or delete a second time.

- [ ] **Step 4: Run reconciler tests.**

Run: `cd control-plane && uv run pytest tests/test_reconciler.py -q`

- [ ] **Step 5: Commit reconciliation behavior.**

```bash
git add control-plane/rudder_cp/services/reconciler.py control-plane/rudder_cp/services/nodes.py control-plane/rudder_cp/main.py control-plane/tests/test_reconciler.py
git commit -m "feat: reconcile node state safely"
```

### Task 4: Package production services for GCP

**Files:**
- Create: `deploy/gcp/control-plane.compose.yml`
- Create: `deploy/gcp/agent.compose.yml`
- Create: `deploy/gcp/rudder-agent.service`
- Create: `deploy/gcp/README.md`
- Test: `deploy/gcp/verify-compose.sh`

- [ ] **Step 1: Write Compose validation commands for both production definitions.**

Run: `docker compose -f deploy/gcp/control-plane.compose.yml config --quiet`

- [ ] **Step 2: Create a control-plane definition without source mounts, reload mode, public database ports, or localhost image references.**

```yaml
services:
  control-plane:
    image: ${RUDDER_CONTROL_PLANE_IMAGE}
    env_file: /etc/rudder/control-plane.env
    ports: ["8000:8000"]
```

- [ ] **Step 3: Create a node-agent definition and systemd unit.**

```yaml
services:
  agent:
    image: ${RUDDER_AGENT_IMAGE}
    env_file: /etc/rudder/agent.env
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - rudder-agent-state:/var/lib/rudder-agent/compose
```

- [ ] **Step 4: Validate both configurations.**

Run: `bash deploy/gcp/verify-compose.sh`

- [ ] **Step 5: Commit deployment artifacts.**

```bash
git add deploy/gcp
git commit -m "ops: package phase 2 GCP runtime"
```

### Task 5: Finish the node and instance UI

**Files:**
- Modify: `web/app/page.tsx`
- Modify: `web/lib/api.ts`
- Modify: `web/lib/queries.ts`
- Modify: `web/lib/types.ts`
- Test: `web/app/page.test.tsx`

- [ ] **Step 1: Add failing UI tests for healthy/unreachable nodes, capacity, and instance-to-node mapping.**

```tsx
expect(screen.getByText("rudder-node-a")).toBeVisible()
expect(screen.getByText("unreachable")).toBeVisible()
```

- [ ] **Step 2: Render server state from `/nodes` without exposing secrets or internal Docker details.**

```tsx
<NodeCard node={node} instances={node.instances} />
```

- [ ] **Step 3: Run web tests, typecheck, and production build.**

Run: `cd web && npm test && npm run typecheck && npm run build`

- [ ] **Step 4: Commit UI state.**

```bash
git add web/app/page.tsx web/lib/api.ts web/lib/queries.ts web/lib/types.ts web/app/page.test.tsx
git commit -m "feat: show multi-host runtime state"
```

### Task 6: Deploy and prove the GCP runtime

**Files:**
- Modify: `docs/phases/checkpoints/PHASE-2-GCP-HANDOFF.md`
- Create: `docs/phases/checkpoints/PHASE-2-VERIFICATION.md`

- [ ] **Step 1: Build and publish immutable control-plane and agent images to a private registry reachable by all VMs.**

```bash
docker build -t "$REGISTRY/rudder-control-plane:$SHA" control-plane
docker build -t "$REGISTRY/rudder-agent:$SHA" agent
docker push "$REGISTRY/rudder-control-plane:$SHA"
docker push "$REGISTRY/rudder-agent:$SHA"
```

- [ ] **Step 2: Install protected environment files and start the control plane and agents through IAP SSH.**

```bash
gcloud compute ssh rudder-control --tunnel-through-iap --command='sudo docker compose -f /opt/rudder/control-plane.compose.yml up -d'
```

- [ ] **Step 3: Verify two nodes are healthy through the authenticated API and UI.**

```bash
curl -fsS http://10.42.0.2:8000/healthz
```

- [ ] **Step 4: Deploy a stateless sample, stop its selected node's agent, and verify replacement on the survivor within 60 seconds.**

Expected: one live replacement instance, no duplicate live route, and the UI
shows the failed node unreachable plus the survivor's healthy instance.

- [ ] **Step 5: Verify a volume-backed service is degraded rather than duplicated after node loss.**

- [ ] **Step 6: Record commands, observed results, and residual limitations in the verification checkpoint.**

- [ ] **Step 7: Commit the verification evidence.**

```bash
git add docs/phases/checkpoints/PHASE-2-GCP-HANDOFF.md docs/phases/checkpoints/PHASE-2-VERIFICATION.md
git commit -m "docs: verify phase 2 multi-host runtime"
```
