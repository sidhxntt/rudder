"""Protected endpoints for durable Kubernetes service-operation intent."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, status
from sqlmodel import Session

from rudder_cp.db import get_session
from rudder_cp.models import OperationKind
from rudder_cp.schemas.common import error_responses, translate_errors
from rudder_cp.schemas.operations import (
    AutoscalingRequest,
    BackupRequest,
    CronJobRequest,
    ObservabilityRequest,
    OneOffJobRequest,
    PlacementRequest,
    ReadReplicaRequest,
    ResourceRequest,
    RestoreRequest,
    RollbackRequest,
    RolloutRequest,
    ScaleOperationRequest,
    ServiceOperationRead,
    StorageResizeRequest,
)
from rudder_cp.services import operations as operation_ops

router = APIRouter(tags=["service-operations"])
SessionDep = Annotated[Session, Depends(get_session)]
IdempotencyKey = Annotated[
    str,
    Header(alias="Idempotency-Key", min_length=1, max_length=256),
]


def _dump(payload: object) -> dict[str, object]:
    # Pydantic's JSON mode makes UUIDs and tuples safe to persist in JSON.
    return payload.model_dump(mode="json")  # type: ignore[union-attr]


async def _submit(
    session: Session,
    *,
    service_id: UUID,
    kind: OperationKind,
    payload: object,
    idempotency_key: str,
    database_only: bool = False,
) -> ServiceOperationRead:
    with translate_errors():
        operation = operation_ops.create_operation(
            session,
            service_id=service_id,
            kind=kind,
            requested=_dump(payload),
            idempotency_key=idempotency_key,
            database_only=database_only,
        )
    return ServiceOperationRead.model_validate(operation)


@router.get(
    "/services/{service_id}/operations",
    response_model=list[ServiceOperationRead],
    responses=error_responses(404, 422),
    operation_id="list_service_operations",
)
async def list_service_operations(
    service_id: UUID, session: SessionDep
) -> list[ServiceOperationRead]:
    with translate_errors():
        rows = operation_ops.list_operations(session, service_id)
    return [ServiceOperationRead.model_validate(row) for row in rows]


@router.post(
    "/services/{service_id}/operations/scale",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=ServiceOperationRead,
    responses=error_responses(404, 409, 422),
)
async def request_scale(
    service_id: UUID,
    payload: ScaleOperationRequest,
    idempotency_key: IdempotencyKey,
    session: SessionDep,
) -> ServiceOperationRead:
    with translate_errors():
        service = operation_ops.get_service(session, service_id)
        requested = operation_ops.normalize_scale_request(service, payload)
        operation = operation_ops.create_operation(
            session,
            service_id=service_id,
            kind=OperationKind.SCALE,
            requested=requested,
            idempotency_key=idempotency_key,
        )
    return ServiceOperationRead.model_validate(operation)


@router.post(
    "/services/{service_id}/operations/resources",
    status_code=202,
    response_model=ServiceOperationRead,
    responses=error_responses(404, 409, 422),
)
async def request_resources(
    service_id: UUID, payload: ResourceRequest, idempotency_key: IdempotencyKey, session: SessionDep
) -> ServiceOperationRead:
    return await _submit(
        session,
        service_id=service_id,
        kind=OperationKind.RESOURCES,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/services/{service_id}/operations/autoscaling",
    status_code=202,
    response_model=ServiceOperationRead,
    responses=error_responses(404, 409, 422),
)
async def request_autoscaling(
    service_id: UUID,
    payload: AutoscalingRequest,
    idempotency_key: IdempotencyKey,
    session: SessionDep,
) -> ServiceOperationRead:
    return await _submit(
        session,
        service_id=service_id,
        kind=OperationKind.AUTOSCALING,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/services/{service_id}/operations/placement",
    status_code=202,
    response_model=ServiceOperationRead,
    responses=error_responses(404, 409, 422),
)
async def request_placement(
    service_id: UUID,
    payload: PlacementRequest,
    idempotency_key: IdempotencyKey,
    session: SessionDep,
) -> ServiceOperationRead:
    return await _submit(
        session,
        service_id=service_id,
        kind=OperationKind.PLACEMENT,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/services/{service_id}/operations/rollout",
    status_code=202,
    response_model=ServiceOperationRead,
    responses=error_responses(404, 409, 422),
)
async def request_rollout(
    service_id: UUID, payload: RolloutRequest, idempotency_key: IdempotencyKey, session: SessionDep
) -> ServiceOperationRead:
    return await _submit(
        session,
        service_id=service_id,
        kind=OperationKind.ROLLOUT,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/services/{service_id}/operations/rollback",
    status_code=202,
    response_model=ServiceOperationRead,
    responses=error_responses(404, 409, 422),
)
async def request_rollback(
    service_id: UUID, payload: RollbackRequest, idempotency_key: IdempotencyKey, session: SessionDep
) -> ServiceOperationRead:
    """Record rollback intent only; the immutable deployment switch is a later reconciler action."""
    return await _submit(
        session,
        service_id=service_id,
        kind=OperationKind.ROLLBACK,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/services/{service_id}/operations/backups",
    status_code=202,
    response_model=ServiceOperationRead,
    responses=error_responses(404, 409, 422),
)
async def request_backup(
    service_id: UUID, payload: BackupRequest, idempotency_key: IdempotencyKey, session: SessionDep
) -> ServiceOperationRead:
    return await _submit(
        session,
        service_id=service_id,
        kind=OperationKind.BACKUP,
        payload=payload,
        idempotency_key=idempotency_key,
        database_only=True,
    )


@router.post(
    "/services/{service_id}/operations/restores",
    status_code=202,
    response_model=ServiceOperationRead,
    responses=error_responses(404, 409, 422),
)
async def request_restore(
    service_id: UUID, payload: RestoreRequest, idempotency_key: IdempotencyKey, session: SessionDep
) -> ServiceOperationRead:
    return await _submit(
        session,
        service_id=service_id,
        kind=OperationKind.RESTORE,
        payload=payload,
        idempotency_key=idempotency_key,
        database_only=True,
    )


@router.post(
    "/services/{service_id}/operations/read-replicas",
    status_code=202,
    response_model=ServiceOperationRead,
    responses=error_responses(404, 409, 422),
)
async def request_read_replica(
    service_id: UUID,
    payload: ReadReplicaRequest,
    idempotency_key: IdempotencyKey,
    session: SessionDep,
) -> ServiceOperationRead:
    return await _submit(
        session,
        service_id=service_id,
        kind=OperationKind.READ_REPLICA,
        payload=payload,
        idempotency_key=idempotency_key,
        database_only=True,
    )


@router.post(
    "/services/{service_id}/operations/storage",
    status_code=202,
    response_model=ServiceOperationRead,
    responses=error_responses(404, 409, 422),
)
async def request_storage(
    service_id: UUID,
    payload: StorageResizeRequest,
    idempotency_key: IdempotencyKey,
    session: SessionDep,
) -> ServiceOperationRead:
    return await _submit(
        session,
        service_id=service_id,
        kind=OperationKind.STORAGE,
        payload=payload,
        idempotency_key=idempotency_key,
        database_only=True,
    )


@router.post(
    "/services/{service_id}/operations/schedules",
    status_code=202,
    response_model=ServiceOperationRead,
    responses=error_responses(404, 409, 422),
)
async def request_schedule(
    service_id: UUID, payload: CronJobRequest, idempotency_key: IdempotencyKey, session: SessionDep
) -> ServiceOperationRead:
    return await _submit(
        session,
        service_id=service_id,
        kind=OperationKind.SCHEDULE,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/services/{service_id}/operations/jobs",
    status_code=202,
    response_model=ServiceOperationRead,
    responses=error_responses(404, 409, 422),
)
async def request_job(
    service_id: UUID,
    payload: OneOffJobRequest,
    idempotency_key: IdempotencyKey,
    session: SessionDep,
) -> ServiceOperationRead:
    return await _submit(
        session,
        service_id=service_id,
        kind=OperationKind.JOB,
        payload=payload,
        idempotency_key=idempotency_key,
    )


@router.post(
    "/services/{service_id}/operations/observability",
    status_code=202,
    response_model=ServiceOperationRead,
    responses=error_responses(404, 409, 422),
)
async def request_observability(
    service_id: UUID,
    payload: ObservabilityRequest,
    idempotency_key: IdempotencyKey,
    session: SessionDep,
) -> ServiceOperationRead:
    return await _submit(
        session,
        service_id=service_id,
        kind=OperationKind.OBSERVABILITY,
        payload=payload,
        idempotency_key=idempotency_key,
    )
