# Phase 1 completion record

Status: complete locally on 2026-07-24.

Phase 1 delivers a single-host PaaS control plane. It runs a control plane,
build agent, private registry, Postgres, and Traefik on one Docker host. The
host is intentionally the scheduling boundary for this phase; multi-host
scheduling and durable runtime-log storage are later-phase work.

## Delivered

- Authenticated project, environment, service, domain, variable, deployment,
  and instance APIs with OpenAPI documentation and a generated Python SDK.
- Git-based builds with language detection, generated Dockerfiles, BuildKit,
  private image registry storage, health checks, and immutable deployment
  records.
- Safe rollout behaviour: a replacement is routed only after it is healthy;
  build or health failures leave the previous live instance serving traffic.
- Traefik routing for generated `*.localhost` service URLs and service-managed
  custom domains.
- Browser UI with login/session handling, a live project canvas, deployment
  history, build logs, variables, and clear failed-deployment/previous-live
  state.
- `rudder` CLI, generated Python SDK, signed GitHub push-webhook deployment,
  and deployment supersession/concurrency protection.
- Runtime-safe service, environment, and project deletion: owned containers
  are removed and Traefik is rendered before database records are deleted.

## Acceptance checks completed

The following were exercised against the local running stack on 2026-07-24:

- Deployed and reached a Node service (`api`) and Python service (`pyapi`) via
  their generated production URLs.
- Verified UI build logs, deployment history, service variables, login, and
  browser navigation.
- Forced a deliberately invalid Dockerfile on an isolated service. Its new
  deployment was marked `failed` while the old live URL continued returning
  HTTP 200. The configuration was restored afterwards.
- Stopped an isolated live container, confirmed its route stopped serving it,
  then redeployed and confirmed recovery.
- Created and deployed a service entirely through the CLI, including streamed
  deploy status and build-log retrieval.
- Created a temporary GitHub repository and signed push webhook. A real push
  returned HTTP 202, built the pushed commit, and changed the deployed
  response. Two near-simultaneous deploy requests resulted in one `live`
  deployment, one `superseded` deployment, and one healthy instance.
- Deleted the temporary services `rollout-test`, `cli-acceptance-e2e`, and
  `webhook-e2e`. Only the intended `api` and `pyapi` production services
  remain. The temporary GitHub webhook was also removed.

The temporary GitHub repository and webhook were deleted after validation. They
are not product requirements.

## Automated validation

Run these commands from the stated package directory:

```sh
# control-plane
uv run --extra dev pytest -q
uv run --extra dev ruff check .

# agent
uv run --extra dev pytest -q
uv run --extra dev ruff check .

# SDK and CLI
cd ../sdk-python && uv build
cd ../cli && uv build && uv run rudder --help

# web
cd ../web && npm run typecheck && npm run build
```

Final results on 2026-07-24:

| Area | Result |
| --- | --- |
| Control plane tests | 255 passed |
| Control plane lint | passed |
| Agent tests | 50 passed |
| Agent lint | passed |
| Python SDK build | source distribution and wheel built |
| CLI build and smoke test | source distribution and wheel built; `rudder --help` passed |
| Web type check | passed |
| Web production build | passed (run in an isolated temporary copy to avoid modifying a running dev server) |

## Cleanup and repeatability

Test deployments and the one-time Cloudflare quick tunnel were intentionally
removed after acceptance testing. To repeat GitHub webhook testing, create a
new disposable repository, use a temporary public tunnel, configure the
existing webhook secret, and delete both artifacts afterwards.

## Phase 2 handoff — multi-host scheduling

Phase 1 is deliberately single-host. Phase 2 must replace the control-plane's
local-agent assumption with a registered-node model while preserving Phase 1's
safe rollout, deployment history, and routing behaviour.

### Prerequisites

- At least two Linux hosts with root or Docker-admin access, reachable from the
  control plane. macOS is not a supported node-agent host.
- SSH access, stable hostnames/IPs, and a shared network plan for control
  plane-to-agent calls and service routing.
- An explicit split-brain policy approved in an ADR: whether a node deemed
  unreachable may be rescheduled before it is conclusively dead. Stateless
  workloads may accept duplicate execution; stateful workloads must not.

### Build in this order

1. **Node registration and heartbeat** — add a `Node` model and API; agents
   register at boot and heartbeat every 5 seconds with capacity and observed
   containers. Mark a node `unreachable` after 30 seconds without a heartbeat.
2. **Idempotent agent API** — expose authenticated create, remove, and list
   container operations. Repeating a request with the same intent/container ID
   must not create a duplicate container.
3. **Transactional scheduler** — filter healthy nodes with enough resources,
   then place onto the lowest allocated-memory ratio. Lock the selected `Node`
   row during the capacity update and `Instance` insert to prevent
   double-booking under concurrent deploys.
4. **Reconciler** — every 10 seconds compare desired instances from live
   deployments with agent-reported actual state. It should create missing
   instances, remove orphans, and do nothing on a second identical pass.
5. **Failure and return handling** — reschedule instances from unreachable
   nodes; when a node returns, stop containers that no longer correspond to a
   desired intent rather than treating them as live state.
6. **UI and CLI** — show node health/capacity and instance-to-node placement;
   add CLI inspection commands for nodes and instances.

### Non-negotiable invariants

- Agents execute placement instructions; they never decide placement.
- Capacity accounting and instance creation occur in one database transaction.
- Reconciler actions are tied to an intent/generation so delayed heartbeats do
  not cause repeated create/stop oscillation.
- The reconciler never issues commands to unreachable nodes.
- Node loss does not delete historical records. A returning node can be
  reconciled safely.
- Multi-host routing must not expose a replacement until the instance is
  healthy, retaining Phase 1's old-live-on-failure guarantee.

### Required tests and acceptance evidence

- Concurrent placement against capacity for exactly one instance: exactly one
  request succeeds, with no over-allocation.
- Stale heartbeat/report scenarios: the reconciler converges without thrash.
- Two identical reconciliation passes: the second issues zero agent commands.
- Two nodes register and report capacity; a second workload chooses the less
  loaded node.
- Stop one node agent and verify its instances reschedule within 60 seconds.
- Restore that node and verify obsolete/orphaned containers are removed with no
  duplicate live instances.
- Let the reconciler run for 10 minutes without changes and verify zero
  container create/remove calls.
- Record the split-brain policy, live-test results, and automated-test results
  in a Phase 2 checkpoint before declaring the phase complete.

See [Phase 2 — Multi-host](../PHASE-2-multi-host.md) for the full target plan
and failure-mode notes.
