"""Dispatch persisted operation intent without ever rebuilding source code.

The API only writes durable desired state.  This worker-side bridge turns that
state into either an immutable-image reconciliation candidate or an instant
rollback of an already healthy immutable deployment.  It deliberately has no
builder dependency: a manual scale, HPA, schedule, or resource change must not
checkout a repository or produce a second image.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlmodel import Session, select

from rudder_cp.config import Settings
from rudder_cp.models import (
    Deployment,
    DeploymentStatus,
    GitHubImport,
    GitHubImportService,
    OperationKind,
    OperationStatus,
    ServiceOperation,
    ServiceOperationsState,
)
from rudder_cp.models.base import utc_now
from rudder_cp.services.rollbacks import restore_immutable_deployment


async def reconcile_pending_rollbacks(session: Session, *, settings: Settings) -> int:
    """Restore requested immutable deployments without a build or a restart."""
    rows = session.exec(
        select(ServiceOperation).where(
            ServiceOperation.kind == OperationKind.ROLLBACK,
            ServiceOperation.status.in_(  # type: ignore[attr-defined]
                [OperationStatus.PENDING, OperationStatus.PROGRESSING]
            ),
        )
    ).all()
    completed = 0
    for operation in rows:
        target_raw = operation.requested.get("deployment_id")
        try:
            target_id = UUID(str(target_raw))
            deployment = await restore_immutable_deployment(
                session, deployment_id=target_id, settings=settings
            )
        except Exception as exc:
            operation.status = OperationStatus.FAILED
            operation.observed = {"status": "failed", "mechanism": "immutable_route_restore"}
            operation.error_message = str(exc)
        else:
            operation.status = OperationStatus.HEALTHY
            operation.observed = {
                "status": "healthy",
                "deployment_id": str(deployment.id),
                "image_tag": deployment.image_tag,
                "mechanism": "immutable_route_restore",
            }
            operation.error_message = None
        operation.completed_at = datetime.now(UTC)
        session.add(operation)
        state = session.exec(
            select(ServiceOperationsState).where(
                ServiceOperationsState.service_id == operation.service_id
            )
        ).first()
        if state is not None:
            state.pending_reconciliation = False
            state.observed = {
                **state.observed,
                "reconciliation": {
                    "pending": False,
                    "applied_version": state.version,
                    "status": operation.status.value,
                },
            }
            state.updated_at = utc_now()
            session.add(state)
        completed += 1
    if completed:
        session.commit()
    return completed


def queue_pending_operation_reconciliations(session: Session) -> list[UUID]:
    """Queue one immutable-image release per imported application.

    Child services share their import's app deployment.  Coalescing pending
    intent by app prevents three edits (for example scale + resources + HPA)
    from producing three source builds or competing candidate releases.
    """
    states = session.exec(
        select(ServiceOperationsState).where(ServiceOperationsState.pending_reconciliation.is_(True))
    ).all()
    queued: list[UUID] = []
    seen_apps: set[UUID] = set()
    for state in states:
        mapping = session.exec(
            select(GitHubImportService).where(GitHubImportService.service_id == state.service_id)
        ).first()
        if mapping is None:
            continue
        imported = session.get(GitHubImport, mapping.github_import_id)
        if imported is None or imported.app_service_id in seen_apps:
            continue
        seen_apps.add(imported.app_service_id)

        # Rollbacks move the existing live pointer and are handled above. They
        # must never become a new candidate deployment.
        pending_non_rollback = session.exec(
            select(ServiceOperation).where(
                ServiceOperation.service_id == state.service_id,
                ServiceOperation.status.in_(  # type: ignore[attr-defined]
                    [OperationStatus.PENDING, OperationStatus.PROGRESSING]
                ),
                ServiceOperation.kind != OperationKind.ROLLBACK,
            )
        ).first()
        if pending_non_rollback is None:
            continue

        in_flight = session.exec(
            select(Deployment).where(
                Deployment.service_id == imported.app_service_id,
                Deployment.status.in_(  # type: ignore[attr-defined]
                    [DeploymentStatus.QUEUED, DeploymentStatus.BUILDING, DeploymentStatus.DEPLOYING]
                ),
            )
        ).first()
        if in_flight is not None:
            continue
        source = session.exec(
            select(Deployment)
            .where(
                Deployment.service_id == imported.app_service_id,
                Deployment.status == DeploymentStatus.LIVE,
                Deployment.image_tag.is_not(None),  # type: ignore[union-attr]
            )
            .order_by(Deployment.became_live_at.desc(), Deployment.created_at.desc())
        ).first()
        if source is None or not source.image_tag:
            # No immutable artifact exists yet. Leave the intent pending until
            # the user performs the first source deployment.
            continue
        candidate = Deployment(
            service_id=imported.app_service_id,
            status=DeploymentStatus.QUEUED,
            image_tag=source.image_tag,
            commit_sha=source.commit_sha,
        )
        session.add(candidate)
        session.flush()
        queued.append(candidate.id)
    if queued:
        session.commit()
    return queued
