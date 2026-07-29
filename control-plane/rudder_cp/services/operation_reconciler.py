"""Persist observed Kubernetes operation outcomes without rebuilding source.

The operations API records user intent independently from deployment history.
This module closes that loop after a Kubernetes runtime has applied or observed
the relevant primitives.  It intentionally never starts a build and never
pretends database-operator features are available when this cluster has none.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlmodel import Session, select

from rudder_cp.models import (
    OperationKind,
    OperationStatus,
    ServiceOperation,
    ServiceOperationsState,
)
from rudder_cp.models.base import utc_now


def mark_runtime_operations_progressing(session: Session, *, service_ids: list[UUID]) -> int:
    """Record that a release has begun applying pending intent.

    This is intentionally a state transition only: it neither queues a source
    build nor changes an immutable deployment. Runtime readiness decides the
    terminal state through :func:`reconcile_runtime_operations`.
    """
    total = 0
    for service_id in service_ids:
        state = session.exec(
            select(ServiceOperationsState).where(ServiceOperationsState.service_id == service_id)
        ).first()
        if state is None or not state.pending_reconciliation:
            continue
        rows = session.exec(
            select(ServiceOperation).where(
                ServiceOperation.service_id == service_id,
                ServiceOperation.status == OperationStatus.PENDING,
            )
        ).all()
        for operation in rows:
            operation.status = OperationStatus.PROGRESSING
            operation.observed = {"status": "progressing"}
            session.add(operation)
            total += 1
        state.observed = {
            **state.observed,
            "reconciliation": {
                "pending": True,
                "requested_version": state.version,
                "status": "progressing",
            },
        }
        state.updated_at = utc_now()
        session.add(state)
    if total:
        session.commit()
    return total


def reconcile_runtime_operations(
    session: Session,
    *,
    service_id: UUID,
    runtime_observed: Mapping[str, Any],
) -> dict[str, int]:
    """Move pending operation audit rows to their observed terminal state.

    Kubernetes workload readiness has already succeeded before this function is
    called. Operator-backed outcomes are only healthy when the runtime returns
    a matching observed state; unavailable features remain explicitly degraded
    instead of being silently reported as healthy.
    """
    state = session.exec(
        select(ServiceOperationsState).where(ServiceOperationsState.service_id == service_id)
    ).first()
    if state is None:
        return {"healthy": 0, "degraded": 0, "failed": 0}

    rows = session.exec(
        select(ServiceOperation).where(
            ServiceOperation.service_id == service_id,
            ServiceOperation.status.in_(  # type: ignore[attr-defined]
                [OperationStatus.PENDING, OperationStatus.PROGRESSING]
            ),
        )
    ).all()
    counts = {"healthy": 0, "degraded": 0, "failed": 0}
    completed_backup_ids: set[str] = set()
    for operation in rows:
        status, observed, error = _observe_operation(operation, runtime_observed)
        operation.status = status
        operation.observed = observed
        operation.error_message = error
        operation.completed_at = datetime.now(UTC)
        session.add(operation)
        if status is OperationStatus.HEALTHY:
            counts["healthy"] += 1
            if operation.kind is OperationKind.BACKUP:
                completed_backup_ids.add(str(operation.id))
        elif status is OperationStatus.DEGRADED:
            counts["degraded"] += 1
        else:
            counts["failed"] += 1

    reconciliation_status = (
        "failed"
        if counts["failed"]
        else "degraded"
        if counts["degraded"]
        else "healthy"
    )
    # A backup is a one-shot action, not durable desired configuration. Once
    # the matching CNPG Backup CRD reaches a terminal state, remove it so an
    # unrelated later scale/resource release cannot execute it again.
    if completed_backup_ids and isinstance(state.desired.get("backups"), Mapping):
        requested_id = state.desired["backups"].get("operation_id")
        if isinstance(requested_id, str) and requested_id in completed_backup_ids:
            state.desired = {key: value for key, value in state.desired.items() if key != "backups"}
    state.pending_reconciliation = False
    state.observed = {
        **state.observed,
        "runtime": dict(runtime_observed),
        "reconciliation": {
            "pending": False,
            "applied_version": state.version,
            "status": reconciliation_status,
        },
    }
    state.updated_at = utc_now()
    session.add(state)
    session.commit()
    return counts


def mark_runtime_operations_failed(
    session: Session,
    *,
    service_ids: list[UUID],
    reason: str,
) -> int:
    """Terminally fail operations started by a release that did not become ready.

    A failed candidate must never leave its immutable operation audit rows in a
    misleading ``progressing`` state.  This does not alter desired intent: a
    user may correct the capacity or configuration issue and request a new
    immutable release later.
    """
    total = 0
    for service_id in service_ids:
        state = session.exec(
            select(ServiceOperationsState).where(ServiceOperationsState.service_id == service_id)
        ).first()
        if state is None:
            continue
        rows = session.exec(
            select(ServiceOperation).where(
                ServiceOperation.service_id == service_id,
                ServiceOperation.status.in_(  # type: ignore[attr-defined]
                    [OperationStatus.PENDING, OperationStatus.PROGRESSING]
                ),
            )
        ).all()
        for operation in rows:
            operation.status = OperationStatus.FAILED
            operation.observed = {"status": "failed", "reason": reason}
            operation.error_message = reason
            operation.completed_at = datetime.now(UTC)
            session.add(operation)
            total += 1
        state.pending_reconciliation = False
        state.observed = {
            **state.observed,
            "reconciliation": {
                "pending": False,
                "applied_version": state.version,
                "status": "failed",
            },
        }
        state.updated_at = utc_now()
        session.add(state)
    if total:
        session.commit()
    return total


def _observe_operation(
    operation: ServiceOperation, runtime_observed: Mapping[str, Any]
) -> tuple[OperationStatus, dict[str, Any], str | None]:
    if operation.kind is OperationKind.READ_REPLICA:
        read_replicas = runtime_observed.get("read_replicas")
        if isinstance(read_replicas, Mapping) and read_replicas.get("status") == "configured":
            return OperationStatus.HEALTHY, {"runtime": dict(runtime_observed)}, None
        reason = (
            "read replica requires a compatible database operator; no configured "
            "read-replica runtime was observed"
        )
        return OperationStatus.DEGRADED, {"status": "degraded", "reason": reason}, reason
    if operation.kind is OperationKind.BACKUP:
        backup = runtime_observed.get("backup")
        if isinstance(backup, Mapping) and backup.get("status") == "completed":
            return OperationStatus.HEALTHY, {"runtime": dict(runtime_observed)}, None
        if isinstance(backup, Mapping) and backup.get("status") == "failed":
            return (
                OperationStatus.FAILED,
                {"runtime": dict(runtime_observed)},
                "PostgreSQL backup failed",
            )
        reason = "PostgreSQL backup did not reach a terminal CloudNativePG state"
        return OperationStatus.DEGRADED, {"status": "degraded", "reason": reason}, reason
    if operation.kind is OperationKind.RESTORE:
        reason = "restore requires a dedicated recovery-cluster cutover and is not enabled"
        return OperationStatus.DEGRADED, {"status": "degraded", "reason": reason}, reason
    if operation.kind is OperationKind.STORAGE:
        storage = runtime_observed.get("storage")
        if isinstance(storage, Mapping) and storage.get("status") == "configured":
            return OperationStatus.HEALTHY, {"runtime": dict(runtime_observed)}, None
        reason = (
            "persistent-volume expansion is not enabled until Rudder verifies the "
            "StorageClass allows volume expansion"
        )
        return OperationStatus.DEGRADED, {"status": "degraded", "reason": reason}, reason
    if operation.kind is OperationKind.ROLLBACK:
        reason = (
            "rollback must restore an existing immutable deployment through the "
            "deployment restore endpoint; this operation did not create a source build"
        )
        return OperationStatus.DEGRADED, {"status": "degraded", "reason": reason}, reason
    if operation.kind is OperationKind.ROLLOUT:
        rollout = runtime_observed.get("rollout")
        if isinstance(rollout, Mapping) and rollout.get("status") == "degraded":
            reason = str(rollout.get("reason", "progressive rollout is not supported"))
            return OperationStatus.DEGRADED, {"runtime": dict(runtime_observed)}, reason
    if operation.kind is OperationKind.JOB:
        job = runtime_observed.get("job")
        if isinstance(job, Mapping) and job.get("status") == "failed":
            return (
                OperationStatus.FAILED,
                {"runtime": dict(runtime_observed)},
                "Kubernetes Job failed",
            )
    return OperationStatus.HEALTHY, {"runtime": dict(runtime_observed)}, None
