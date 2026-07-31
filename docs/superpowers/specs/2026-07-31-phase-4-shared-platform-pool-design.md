# Phase 4 shared platform pool design

**Status:** approved — 2026-07-31  
**Scope:** operate GKE within the current project-wide 12-vCPU
`CPUS_ALL_REGIONS` limit.

## Decision

Rudder will not create the optional `workloads` node pool while the project has
only 12 aggregate vCPUs. Customer application Pods will instead run on the
existing regional `platform` pool alongside the Rudder control-plane and edge
components.

The live cluster currently has two regional `e2-standard-2` pools:

- `system` — 6 vCPUs, untainted, reserved in practice for GKE-managed
  components such as CoreDNS.
- `platform` — 6 vCPUs, labelled `rudder.pool=platform` and tainted
  `rudder.pool=platform:NoSchedule`.

The `platform` pool remains tainted. Rudder-generated customer workloads must
explicitly select `rudder.pool=platform` and tolerate that exact taint. This
avoids scheduling them onto the system pool while allowing the existing capacity
to serve the first production/beta workloads without a third pool.

## Safety boundaries

- Namespaces, per-environment `ResourceQuota`, `LimitRange`, NetworkPolicies,
  immutable images, readiness gates, and deployment rollback semantics remain
  mandatory.
- Platform services retain a higher priority class than customer workloads so
  that a resource-pressure event evicts customer workloads first.
- Customer workloads receive requests and limits. A deployment that cannot fit
  in the platform pool remains Pending and is reported as capacity constrained;
  it must not displace the control plane silently.
- Stateful services retain their existing private Service, persistent-volume,
  and NetworkPolicy rules. No database is made publicly reachable by this
  decision.

## Explicit limitation

This is an initial-production / beta topology, not durable compute isolation
between Rudder platform Pods and customer Pods. It is acceptable only while the
customer workload count and resource budgets are small and actively monitored.

## Upgrade path

When the project-wide `CPUS_ALL_REGIONS` quota permits at least 18 vCPUs,
enable the existing Terraform `workloads` pool. Then update only the generated
customer-workload node selector and toleration from `platform` to `workloads`.
The user-facing deployment model, environment DNS, immutable artifacts, and
rollback API do not change.

## Verification

1. Terraform plan with `enable_workloads_pool=false` must make no cloud
   infrastructure changes.
2. A generated application, worker, and private datastore release must schedule
   on platform-labelled nodes; no customer workload may run on system nodes.
3. Resource-pressure test must preserve control-plane and ingress Pods while
   rejecting or evicting the lower-priority customer workload.
4. Existing GKE API checks must still report `CPUS_ALL_REGIONS = 12` and no
   third node pool.
