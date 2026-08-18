# Phase 6: day-two operations

> **Status:** core mechanics are implemented and automated. Some end-to-end Docker/GKE exercises remain the authoritative operational acceptance evidence.

## Goal and plan

Earlier phases could create a release; Phase 6 made releases operable after deployment. The plan added durable-state rules, managed database templates, bounded logs and metrics, and immutable rollback. The key design principle was to keep each feature proportionate: Rudder is a control plane, not a replacement for a full monitoring vendor.

## Design

### Volumes and databases

Volumes are pinned to a node in the Docker runtime. A volume-backed service cannot be silently moved to a different node after failure because it could start empty and corrupt an operator’s understanding of its data. Such services are limited to one replica. Service deletion requires an explicit decision and does not default to deleting data.

Postgres, Redis, and MySQL templates produce database-kind services with generated credentials stored through the normal encrypted-variable path. Regeneration on redeploy is forbidden: dependent services would otherwise lose connectivity. Database-kind services are private by default and do not receive public routing.

On the production Kubernetes path, Phase 4’s CloudNativePG contract supersedes a hand-built Postgres StatefulSet for durable workload data. PVC deletion is deliberately outside normal Rudder authority.

### Logs, metrics, and rollback

Runtime log collection reads bounded snapshots from agents for Docker and pod logs through the Kubernetes API for Kubernetes. A rotating store records truncation/dropped bytes rather than growing without limit; browser and CLI viewers can use SSE/snapshots. This treats high-volume logging as an availability risk rather than assuming disk is infinite.

Metrics are sampled at 10 seconds and compacted: raw for one hour, minute buckets for one day, five-minute buckets for seven days, then expired. This creates canvas/CLI observability without operating Prometheus for the initial scale. Kubernetes uses metrics-server data; temporary metrics/API failure is best-effort and must never halt deployments.

Rollback re-promotes a prior healthy immutable Deployment by changing the service’s system-domain target. It reuses a running release where possible and must not rebuild an image. Permanent deployment URLs remain pinned to their own release.

## Difficult parts and answers

| Problem | Answer |
| --- | --- |
| Scheduler “helpfully” moves stateful service | hard volume pin plus explicit unavailable state |
| crash loops flood control plane | bounded log reads/rotation and visible loss accounting |
| telemetry table grows forever | fixed retention tiers and compaction job |
| old release route points at GC’d image | immutable release/tag discipline and readiness before routing |
| stateful teardown could erase workload data | Kubernetes RBAC and explicit break-glass state deletion path |

## GCP/cost impact

The early Docker lab uses local/named volume capacity. GKE production changes the cost and risk model: PVs consume persistent-disk capacity; CloudNativePG replication and WAL/object backup consume storage/network; metrics-server and log storage consume platform resources. Keeping logs locally bounded avoids an early object-storage bill but limits retention and central query capability. The team chose this consciously; a future scale phase can add an external logging/metrics backend without changing deployment truth.

## Verification and limits

Automated tests cover placement constraints, templates/credential stability, log retention/backpressure, metric compaction, Kubernetes observability, and route rollback. For real acceptance, create a database row, redeploy, confirm it remains; kill a pinned node and prove no relocation; generate excessive logs and check control-plane health/drop reporting; and restore an old live release with no build. The operational commands and requirements are consolidated in this retrospective.
