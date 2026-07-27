# ADR 0003 — Phase 2 node-loss recovery is stateless-only

**Date:** 2026-07-27
**Status:** Accepted

## Context

In the Phase 2 Docker multi-host runtime, an agent can become unreachable
while its host and containers continue running. Starting a second copy of a
workload automatically is safe only when the workload has no host-local
persistent state.

## Decision

- After 30 seconds without a heartbeat, mark the node and its instances
  `unreachable`.
- Automatically queue one replacement only for a service with no `Volume`
  records. The normal scheduler selects another healthy node.
- Never send a stop/remove command to an unreachable node.
- Do not automatically reschedule a service with a persistent volume. It
  remains unavailable until an operator fences or restores the original node
  and performs a state-aware recovery.
- When an unreachable node returns, the reconciler may remove only
  Rudder-labelled orphan containers; it never touches arbitrary Docker
  containers.

## Consequences

Stateless web and worker services recover automatically in the Phase 2 lab.
Databases and other stateful workloads trade automatic availability for data
integrity. Kubernetes/Phase 2.5 is the path for durable storage, fencing, and
production-grade stateful failover.
