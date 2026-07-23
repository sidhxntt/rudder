# Phase 2 — Multi-host

**Target:** 3–4 weeks

**Demo:** two nodes, a service is scheduled onto the less loaded one, that node
dies, the service reschedules.

**This is the hard phase.** Everything before it is plumbing; everything after
it depends on this being correct. Code that looks right here is routinely wrong
under load.

---

## Prerequisites

- [ ] Phase 1 verified end to end
- [ ] Two or more Linux hosts with root — see `../NEED-FROM-YOU.md` item 9.
      **macOS cannot host node agents.**
- [ ] SSH access and hostnames/IPs for each

---

## Steps

### 1. Node agent

Standalone Python service. aiohttp. Registers with the control plane on boot,
then heartbeats every 5s carrying current capacity and the actual state of every
container it is running.

If D3 = (b), most of this already exists from Phase 1 and this step is about
making it register and heartbeat rather than writing it from scratch.

The agent **never makes placement decisions.** It executes instructions and
reports what it observes. That's the core invariant from `../PRD.md` →
"Architecture".

### 2. Agent API

Control plane → agent:

| Endpoint | Does |
|---|---|
| `POST /containers` | create + start |
| `DELETE /containers/{id}` | stop + remove |
| `GET /containers` | list actual state |

Shared secret auth. mTLS is out of scope.

Every endpoint must be **idempotent**. `POST /containers` with an ID that already
exists returns the existing container, it does not create a second one. The
reconciler will retry, and it must be safe to.

### 3. Scheduler

Given a Service needing N replicas:

1. Filter nodes: `status=healthy`, sufficient free CPU and memory
2. Exclude nodes that do not have the required Volume (Phase 5, but the
   constraint hook goes in now)
3. Pick the lowest allocated-memory ratio

**Take a row lock on `Node` during placement.** This is the
concurrency-critical path. Two deploys scheduling simultaneously against the same
node will both read the same free capacity and both place, overcommitting the
node, unless the read is inside a lock.

```sql
SELECT * FROM nodes WHERE id = ... FOR UPDATE
```

Capacity accounting (`cpu_allocated`, `memory_allocated_mb`) is updated in the
same transaction as the Instance insert. Never in a separate call.

### 4. Reconciler

Every 10s: compare desired Instances (derived from live Deployments) to actual
(from agent reports). Start what is missing, stop what is orphaned.

Three properties, all required:

- **Idempotent.** Running it twice with no state change does nothing the second
  time.
- **Convergent under stale reads.** Idempotent is not sufficient. Agent reports
  are seconds old by definition. The reconciler must not act on a stale view in a
  way that creates work it will immediately undo.
- **Refuses to act on unreachable nodes.** No heartbeat in 30s → mark
  `unreachable`, do not attempt to reconcile against it.

### 5. Node failure

No heartbeat for 30s → `status=unreachable` → reschedule its Instances elsewhere.

**Do not delete records.** The node may come back. When it does, it will report
containers that the control plane has already rescheduled — the reconciler must
recognize those as orphaned and stop them, not panic.

### 6. UI

Node list with capacity bars. Instance-to-node mapping shown on the canvas.

---

## Where this goes wrong

This section is longer than the steps for a reason.

**Reconciler thrash.** Control plane wants 2 replicas. Node reports 1. Reconciler
starts one. But the report was 3s stale and there were already 2 — now there are
3. Next tick it stops 2. Then starts one. Forever.

Fix: instances carry a generation or an intent ID; the reconciler acts on
observed-state versions, not raw counts. **"Idempotent" does not solve this** —
each individual action is idempotent and the loop still oscillates.

**Double-booking.** Two deploys, same node, simultaneous capacity read. Both see
4GB free, both place a 3GB service. Row lock (step 3). Write a test that actually
runs them concurrently — `asyncio.gather` on two coroutines that never actually
interleave at the DB proves nothing.

**Split brain.** The node is alive and running containers, but the control plane
cannot reach it. Rescheduling elsewhere means the workload now runs twice. For a
stateless service that's degraded-but-fine; for anything with a volume it's
corruption. Decide the policy explicitly and write it down: reschedule
aggressively, or refuse until the node is confirmed dead.

**Node returns from the dead.** It comes back holding containers for Deployments
that have since been superseded. Reconciler must stop them cleanly rather than
treating them as desired state.

**Heartbeat timing under load.** 30s unreachable threshold with a 5s heartbeat
gives 6 missed beats of slack. Under network jitter or agent GC pause that
threshold can trip on a healthy node. Test with artificial delay injected.

---

## Verify

```bash
# 1. Two nodes register and heartbeat
rudder node list
# → both healthy, capacity reported

# 2. Placement picks the less loaded node
#    deploy a large service to node A, then a second service
rudder deploy svc-b
rudder instance list svc-b
# → lands on node B

# 3. Node failure and reschedule, within 60s
docker stop rudder-agent   # on node A
watch rudder instance list
# → instances move to node B within 60s

# 4. Node returns, stale containers are cleaned up
docker start rudder-agent
# → node A rejoins, its orphaned containers are stopped, no duplicates

# 5. No thrash. Let the reconciler run 10 minutes with no changes.
#    Count container create/delete calls. Expected: zero.
```

Automated, and these are the tests that matter:

- Concurrent placement against a single node with capacity for exactly one
  service. Exactly one placement must succeed.
- Reconciler fed deliberately stale agent reports. Must converge, must not
  oscillate.
- Reconciler run twice on identical state. Second run issues zero commands.

---

## Done when

- [ ] Two nodes register, heartbeat, and report accurate capacity
- [ ] Scheduler places on the less loaded node
- [ ] Killing an agent reschedules its instances within 60s
- [ ] A returning node's orphaned containers are cleaned up
- [ ] Reconciler idle for 10 minutes issues zero commands
- [ ] Concurrent placement test passes — no double-booking
- [ ] Stale-report convergence test passes — no oscillation
- [ ] Split-brain policy written down in an ADR
- [ ] `README.md` Phase 2 section
