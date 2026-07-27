# Phase 2 failover verification

**Verified:** 2026-07-27
**Branch:** `phase-1`
**Result:** Passed for the Phase 2 multi-host control-plane and worker runtime.

## Scope

This checkpoint validates the desired-state, scheduler, heartbeat, and
reconciliation path on the existing two-worker GCP lab. It deliberately does
not claim public-URL failover, because Phase 2 has no shared multi-host ingress
yet.

## Test performed

1. Confirmed that both worker agents were registered and reporting healthy
   five-second heartbeats to the control plane.
2. Confirmed an eligible stateless `source-app` workload was running on worker
   node B.
3. Stopped node B's Rudder agent to simulate loss of the node-control channel.
4. Waited past the 30-second stale-heartbeat threshold.
5. Confirmed that the control plane marked node B unreachable and marked the
   previously live instance unreachable.
6. Confirmed the reconciler created one replacement immutable deployment.
7. Confirmed the scheduler selected healthy node A and the replacement became
   `live` with a `healthy` instance there.
8. Restarted node B's agent and confirmed that both nodes resumed healthy
   heartbeat status.

## Observed result

| Check | Result |
| --- | --- |
| Agent registration and heartbeat | Both nodes healthy before and after the test |
| Failed-node detection | Node B became `unreachable` after the heartbeat timeout |
| Desired-state recovery | The previous node-B instance became `unreachable` |
| Reconciliation | Exactly one replacement deployment was queued |
| Scheduling | Replacement was placed on node A |
| Workload health | Replacement deployment and instance became `live` / `healthy` |
| Recovery cleanup | Node B agent was restarted and healthy at test completion |

The promoted replacement deployment was created at 14:02:57 UTC and ran on
node A. The original deployment was superseded rather than reused, preserving
the immutable-deployment model.

## Important boundary

The Phase 2 lab does **not** provide a shared public ingress or load balancer.
Application containers are private to their worker's Docker network, so this
test cannot verify that one unchanged public URL remains reachable across a
worker failure.

That final availability test belongs to the Phase 2.5 Kubernetes/Gateway or
equivalent GCP load-balancer implementation. It must include a health-aware
shared ingress before Rudder can claim public failover semantics.

## Follow-up checks before production exposure

- Verify that the restored node's obsolete superseded container is drained so
  no duplicate stateless workload remains after recovery.
- Exercise the stateful-workload policy: services with persistent volumes must
  not be automatically duplicated after a node failure.
- Add shared ingress, TLS, and a stable public domain, then repeat this test
  while continuously requesting the public URL.
- Add a dedicated automated GCP integration test for the heartbeat timeout and
  scheduler replacement path.
