# Phase 5: environments, cloning, and pull-request lifecycles

> **Status language.** “Implemented and covered” means repository code and automated tests exist. “Live acceptance outstanding” means it still needs a real runtime demonstration. This document is a retrospective of the implemented project, not a promise that every cloud acceptance exercise has happened.

## Why this phase existed

A project normally needs more than one copy of its service graph: production, a staging area, and temporary pull-request (PR) environments. Copying containers manually is unsafe because connections, databases, domains, and historical runtime objects can accidentally cross environments. Phase 5 made **Environment** a first-class, project-owned graph boundary.

The plan was deliberately database-first: copy a declarative graph, make the copy internally consistent, then allow it to be deployed. It did not copy running processes or data. That makes a clone understandable, repeatable, and safe to delete.

## Design adopted

### A graph clone, not a machine snapshot

`clone_environment` creates a target Environment in one SQL transaction. It copies services (including canvas coordinates), encrypted variable records, managed-service capability metadata, imported-Compose mappings, and volume declarations. It deliberately omits deployments, instances, logs, metrics, user-owned domains, node affinity, and volume contents. A new deploy creates fresh runtime state and, on Kubernetes, fresh PVCs.

Variables can use `${{ServiceName.KEY}}`. Resolution is scoped to services in the same environment, so cloned references retain their names while naturally resolving to the cloned database/cache rather than production. The variable graph is checked for cycles on write; forward references are legal but fail clearly if still unresolved at deploy time.

System domains are recreated for the target. Compose imports receive a new Compose project name and service-ID mapping, preventing preview and production releases from sharing a Compose namespace.

### Isolation and deletion

Kubernetes is the production isolation model described in the [architecture guide](../architecture.md): an environment maps deterministically to a namespace. Namespace guardrails include default-deny networking, resource quota, and limit range. The old WireGuard subnet concept is intentionally deprecated and remains null. Docker remains a development/lab runtime, so it cannot claim the same network isolation.

Destroy is ordered: remove runtime containers when relevant; wait for Kubernetes namespace deletion; then purge catalog rows and render routes. Namespace deletion is time-bounded and returns a retryable 503 instead of forgetting a DB row while PVCs, ingress, or finalizers are still alive. This prevents silent cost/resource leaks.

### GitHub PR environments

Signed `pull_request` webhooks use the PR number as an idempotency key. Open/reopen/synchronize clones the production graph with the PR branch and queues release-owner deployment; duplicate deliveries do not create duplicates. Closed PRs remove the matching environment. PR environments are capped by configuration because each one can consume real CPU, memory, storage and load-balancer/DNS capacity.

The user receives a queued URL comment and, after health-gated live state, a ready comment. Ready notification delivery is persisted in an outbox and retried with backoff; GitHub outages cannot alter health or routing.

## Challenges and resolutions

| Risk | Resolution |
| --- | --- |
| Half-created clone | one transaction and rollback on any copy failure |
| Production data copied into disposable preview | copy only volume declarations; no contents or affinity |
| Repeated/reordered webhooks | PR-number idempotency and idempotent destruction |
| Compose child IDs still point at source | recreate mappings and rewrite `managed_by_service_id` |
| Namespace appears deleted while stuck terminating | wait with a monotonic timeout; leave catalog state retriable |
| PRs exhaust cluster capacity | enforce a configured per-project PR limit |

## Cloud, cost, and operations

On GKE, each clone adds namespace-scoped objects, possible PVCs after deployment, ingress/DNS/certificate work for public services, and workload resource requests. A PR with a database is not “free”: storage and backup/WAL implications can dominate. The cost control is therefore a product constraint (limit and cleanup), not merely billing reporting. Phase 5 deliberately does not clone production volume data; it protects data but means staging tests need fixtures/migrations rather than production snapshots.

## Evidence and remaining limits

Implemented coverage includes atomic copy/rollback, reference rewiring and cycles, Compose mapping cloning, PR idempotency/cleanup, and namespace teardown error handling. The phase specification and governing transaction decision are consolidated in this retrospective.

Live proof should still exercise a real PR lifecycle: open, verify separate namespace/PVC/domain and branch deployment, close, then verify all resources are actually gone. That is stronger evidence than unit tests and is particularly important after cluster/version changes.
