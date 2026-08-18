# Phase 2 — Multi-host Docker scheduling and reconciliation

> **Evidence status:** the GCP two-worker lab failover drill passed on
> 2026-07-27. It is a scheduler/control-plane proof, not proof of uninterrupted
> public traffic across hosts.

## Why this phase existed

Phase 1 could safely roll one host but could not decide where replicas belong
or recover after that host loses its agent. Phase 2 separated **intent** from
**execution**: the control plane chooses placement; a small Linux-host agent
creates/removes containers and reports observations. The agent never schedules.

The plan was node registration and five-second heartbeats, an idempotent agent
API, transactionally safe placement, a ten-second reconciler, and explicit
node-loss policy. The source plan, split-brain decision, and failover evidence
are consolidated in this retrospective.

## Design

### Scheduler and capacity accounting

Eligible nodes must be healthy and have enough CPU/memory; the policy chooses
the lowest allocated-memory ratio. Selection locks the `Node` row, updates
capacity, and creates the `Instance` in one transaction. That prevents two
simultaneous deploys from both observing the same free capacity and
overcommitting it.

### Agent and reconciler

Agents expose authenticated, idempotent create/delete/list endpoints. Every
heartbeat includes capacity and observed containers. The reconciler compares
durable desired instances with observed state. It must be idempotent *and*
generation-aware: stale reports otherwise create a missing replica which the
next stale report removes, causing endless thrash. Current remediation adds
heartbeat/intent generations to fence delayed reports.

### Failure policy

After 30 seconds without a heartbeat, the node and its instances are marked
unreachable. Rudder never commands an unreachable host. It automatically
replaces only stateless services (no `Volume` records); stateful workloads stay
unavailable until an operator fences/restores them. On return, only
Rudder-labelled orphan containers can be removed. This explicitly favours data
integrity over automatic stateful availability.

## Problems encountered and solutions

The central lesson was that “idempotent” is insufficient under delayed data.
Intent/generation fencing, durable instance status, and conservative behaviour
on unreachable nodes prevent oscillation and split-brain cleanup mistakes.
Database row locks solve double booking; tests must actually interleave
transactions rather than merely call two coroutines. A subsequent audit also
found stale-heartbeat races and replica-count gaps, which were remediated with
generation-aware handling and replica-aware standard Docker deployment.

## GCP, operations, and cost

The verified lab used two GCP worker VMs. This added VM, disk, networking, and
operational cost without a shared production ingress. It was retained as a
valuable lab for scheduler correctness, but not promoted to the public runtime.
The absence of a cross-host private network and shared edge is intentional:
building a WireGuard mesh would duplicate what the later Kubernetes platform
already provides.

## Evidence and limits

The recorded drill stopped node B's agent, waited beyond the stale threshold,
observed one replacement scheduled onto node A, and restarted B successfully.
It did not prove an unchanged public URL survived because containers remained
private to each worker Docker network. Required continuing tests include
concurrent one-slot placement, stale-report convergence, an idle reconciler
issuing zero commands, return cleanup, and stateful recovery handling.

## Handoff

Phase 2 established desired state, health-gated deployment history, capacity
accounting, and reconciliation. Kubernetes later replaced host scheduling and
networking in the production path while preserving these product-level
invariants.
