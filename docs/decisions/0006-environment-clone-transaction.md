# ADR 0006 — Clone environment graphs atomically

**Status:** accepted

## Context

Phase 5 creates staging and pull-request environments by copying a production
service graph. A partial clone is dangerous: it looks usable in the UI yet may
be missing a database, variable, domain, or Compose graph member. Copying a
volume's data is also unsafe because it can turn production data into an
untracked disposable database.

## Decision

Rudder performs an environment clone in one database transaction. It copies
services, their canvas positions, encrypted variables, managed capability
metadata, imported-Compose graph mappings, and volume declarations. The copied
volume has no node affinity and no data; the runtime creates a fresh PVC/data
directory on deploy. System domains are regenerated under the target
environment name. Deployments, instances, logs, user domains, and historical
runtime state are omitted.

Reference expressions keep their service/key names unchanged. Resolution is
environment-scoped, so the copied graph automatically resolves against its own
services. Every variable write checks the resolvable reference graph for cycles
before commit; unresolved forward references remain legal and fail clearly at
deploy time.

GitHub PR environments use the PR number as their durable idempotency key. The
same signed webhook can therefore be delivered repeatedly without creating a
second environment; a repeated close is a successful no-op.

## Consequences

- A failed clone leaves no target environment or child records behind.
- Cloned data stores always start empty, preserving production-data isolation.
- Imported Compose projects receive a fresh project name and rewired service
  mapping, so production and preview releases cannot collide at runtime.
- PR environment count is capped by configuration because each clone can
  consume real runtime capacity.
