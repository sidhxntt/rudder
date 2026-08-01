# ADR 0004 — Kubernetes networking replaces the WireGuard mesh

**Date:** 2026-07-29
**Status:** Accepted
**Supersedes:** the WireGuard portion of the original Phase 3/Phase 4 plan.

## Context

The original roadmap gave Rudder its own private service network: a WireGuard
mesh across Docker hosts, with a `wg_subnet` per environment, a `wg_ip` per
instance and node, and peer/key lifecycle management in the control plane.

Phase 3 then made Kubernetes the production runtime and shipped a runtime adapter
verified on Kind. That runtime already provides everything the mesh was for:

- **Private addressing** — ClusterIP Services, no host ports.
- **Name resolution** — CoreDNS, `<service>.<namespace>.svc.cluster.local`.
- **Environment isolation** — one namespace per environment with a default-deny
  NetworkPolicy, plus ResourceQuota and LimitRange.
- **Controlled public exposure** — an Ingress/Gateway route only for a service
  explicitly marked public.

Keeping WireGuard would mean building and operating a second, overlapping private
network whose failure mode is silent (a peer simply stops routing) and whose key
and IP lifecycle is ours to get right. It also cannot be reused: EKS and AKS have
the same Kubernetes networking, so mesh code buys nothing on the multi-cloud path.

## Decision

1. **Rudder does not implement WireGuard.** No peer management, no key rotation,
   no mesh IP allocation, no host-level DNS zones. The private service network is
   Kubernetes networking.
2. **Phase 4 is repurposed** to the GKE production landing zone. It carries the
   Phase 3 resource contract unchanged onto a private regional GKE Standard
   cluster and adds Artifact Registry, Workload Identity, a single managed HTTPS
   edge, durable managed state, observability, and infrastructure-as-code.
   `docs/phases/PHASE-4-mesh.md` keeps its filename **only** to preserve inbound
   links.
3. **The `wg_*` data-model fields are deprecated.** `Environment.wg_subnet`,
   `Node.wg_public_key`, `Node.wg_ip`, and `Instance.wg_ip` stay in the schema as
   nullable columns and must end up always null. Nothing may read or validate
   them, and no new code may depend on them.
4. **The subnet allocator must be removed.** It is not dormant — it is live and
   pointless: `create_environment` calls `allocate_wg_subnet` on every
   environment create, `EnvironmentRead` publishes `wg_subnet` in the API
   response, and three tests in `control-plane/tests/test_crud.py` assert
   distinct-subnet and freed-slot-reuse behaviour. Removing it therefore also
   removes a field from the public API response and deletes those tests. Doing so
   is intended: no consumer routes on it, and leaving it in advertises a network
   isolation guarantee Rudder does not provide. Affected files:
   `control-plane/rudder_cp/services/environments.py` (`allocate_wg_subnet`,
   `SUBNET_POOL_EXHAUSTED`, `_SUBNET_*` pool constants),
   `control-plane/rudder_cp/schemas/environment.py` (`wg_subnet` on
   `EnvironmentRead` plus its docstrings),
   `control-plane/rudder_cp/routers/environments.py` (the "`wg_subnet` is
   server-owned" API description), and `control-plane/rudder_cp/models/project.py`
   (docstring; the column itself stays).
   Environment clone (Phase 5) allocates a namespace, not a subnet.
5. **The Docker runtime is retained as the Phase 1–2 lab path**, not deleted. It
   keeps `Node`, the scheduler, the reconciler, and Traefik. It gains no
   networking work and is not the production target.
6. **WireGuard may return only** if a customer requirement appears for
   non-Kubernetes Docker hosts needing cross-host private networking. That would
   be a new phase with its own ADR, not a resumption of this one.

## Consequences

- Phase 4's cost moved from 2–3 weeks of mesh plumbing to 3–5 weeks of cloud
  landing-zone work. Different work, and none of it is throwaway.
- Environment isolation is now enforced by the cluster, so it is testable with
  ordinary Kubernetes assertions instead of packet-level inspection.
- Cross-host private networking on plain Docker hosts is no longer a Rudder
  feature. Phase 2 stays an internal lab runtime with no public cross-host URLs.
- The multi-cloud path gets cheaper: the workload adapter is shared across GKE,
  EKS, and AKS because all three speak the same Kubernetes networking.
- Four deprecated columns remain in a pre-production schema (`0001_initial_schema`
  creates all of them nullable). Accepted deliberately: a migration to drop them
  costs more review than it saves, and the PRD marks them dead. Drop them the next
  time that schema is migrated anyway.
- `EnvironmentRead.wg_subnet` disappears from the API response when decision 4 is
  carried out. This is a breaking response-schema change, taken now while there
  are no external consumers rather than later.
