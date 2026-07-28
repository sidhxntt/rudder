"""Durable desired state and immutable audit history for service operations.

The control plane accepts intent transactionally.  The Kubernetes reconciler is
deliberately a later concern: it consumes ``pending_reconciliation`` and writes
the observed state after applying a version.  This keeps API retries safe and
prevents a source build from being coupled to manual operations.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from rudder_cp.models import (
    Deployment,
    DeploymentStatus,
    Environment,
    OperationKind,
    OperationStatus,
    Project,
    Service,
    ServiceKind,
    ServiceOperation,
    ServiceOperationsState,
)
from rudder_cp.models.base import utc_now
from rudder_cp.schemas.common import ConflictError, InvalidRequestError, NotFoundError
from rudder_cp.schemas.operations import (
    ScaleOperationRequest,
    ScaleRequest,
    ServiceOperationsIntent,
)

_APP_ONLY_KINDS = {
    OperationKind.AUTOSCALING,
    OperationKind.PLACEMENT,
    OperationKind.ROLLOUT,
    OperationKind.JOB,
}

_APP_ONLY_INTENT_FIELDS = {"autoscaling", "placement", "rollout", "schedules", "last_job"}
_DATABASE_ONLY_INTENT_FIELDS = {"backups", "restore", "read_replicas", "storage"}


def _require_service(
    session: Session, service_id: uuid.UUID, *, owner_id: uuid.UUID | None = None
) -> Service:
    service = session.get(Service, service_id)
    if service is None:
        raise NotFoundError(
            f"service {service_id} does not exist", details={"service_id": str(service_id)}
        )
    if owner_id is not None:
        environment = session.get(Environment, service.environment_id)
        project = session.get(Project, environment.project_id) if environment is not None else None
        if project is None or project.owner_id != owner_id:
            raise NotFoundError(
                f"service {service_id} does not exist", details={"service_id": str(service_id)}
            )
    return service


def get_service(
    session: Session, service_id: uuid.UUID, *, owner_id: uuid.UUID | None = None
) -> Service:
    return _require_service(session, service_id, owner_id=owner_id)


def _state_for(session: Session, service: Service) -> ServiceOperationsState:
    state = session.exec(
        select(ServiceOperationsState).where(ServiceOperationsState.service_id == service.id)
    ).first()
    if state is not None:
        return state
    state = ServiceOperationsState(service_id=service.id)
    session.add(state)
    session.flush()
    return state


def _request_hash(
    *, service_id: uuid.UUID, kind: OperationKind, requested: dict[str, Any], key: str
) -> str:
    canonical = json.dumps(
        {
            "service_id": str(service_id),
            "kind": kind.value,
            "requested": requested,
            "idempotency_key": key,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _database_role(service: Service) -> str:
    role = service.build_config.get("data_role")
    return "read_replica" if role == "read_replica" else "primary"


def _require_database(service: Service, kind: OperationKind) -> None:
    if service.kind is not ServiceKind.DATABASE:
        raise InvalidRequestError(
            f"{kind.value} operations require a database service",
            details={"service_id": str(service.id), "service_kind": service.kind.value},
        )


def _require_app(service: Service, kind: OperationKind) -> None:
    if service.kind is not ServiceKind.APP:
        raise InvalidRequestError(
            f"{kind.value} operations require an application service",
            details={"service_id": str(service.id), "service_kind": service.kind.value},
        )


def normalize_scale_request(service: Service, payload: ScaleOperationRequest) -> dict[str, Any]:
    try:
        normalized = ScaleRequest(
            replicas=payload.replicas,
            service_kind=service.kind,
            data_role=_database_role(service),
        )
    except ValidationError as exc:
        raise InvalidRequestError(
            "manual scale cannot target database primaries",
            details={"service_id": str(service.id)},
        ) from exc
    return {"replicas": normalized.replicas}


def normalize_rollback_request(
    session: Session, *, service: Service, deployment_id: uuid.UUID
) -> dict[str, Any]:
    """Only an immutable live/superseded artifact of this service can be restored.

    The returned intent expressly tells a later reconciler to repoint traffic;
    no build is requested or implied by this API action.
    """
    deployment = session.get(Deployment, deployment_id)
    if deployment is None or deployment.service_id != service.id:
        raise NotFoundError(
            f"deployment {deployment_id} does not exist for service {service.id}",
            details={"deployment_id": str(deployment_id), "service_id": str(service.id)},
        )
    if deployment.status not in {DeploymentStatus.LIVE, DeploymentStatus.SUPERSEDED}:
        raise InvalidRequestError(
            "rollback target must be a live or superseded immutable deployment",
            details={"deployment_id": str(deployment.id), "status": deployment.status.value},
        )
    if not deployment.image_tag:
        raise InvalidRequestError(
            "rollback target has no immutable image artifact",
            details={"deployment_id": str(deployment.id)},
        )
    return {
        "deployment_id": str(deployment.id),
        "image_tag": deployment.image_tag,
        "execution": "pending_runtime_reconciliation",
        "build": "not_requested",
    }


def _deep_merge(base: dict[str, Any], changes: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in changes.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _touch_pending(state: ServiceOperationsState) -> None:
    state.version += 1
    state.pending_reconciliation = True
    state.observed = {
        **state.observed,
        "reconciliation": {
            "pending": True,
            "requested_version": state.version,
        },
    }
    state.updated_at = utc_now()


def _desired_after_operation(
    desired: dict[str, Any], kind: OperationKind, requested: dict[str, Any]
) -> dict[str, Any]:
    next_desired = deepcopy(desired)
    mapping = {
        OperationKind.SCALE: "replicas",
        OperationKind.RESOURCES: "resources",
        OperationKind.AUTOSCALING: "autoscaling",
        OperationKind.PLACEMENT: "placement",
        OperationKind.ROLLOUT: "rollout",
        OperationKind.BACKUP: "backups",
        OperationKind.RESTORE: "restore",
        OperationKind.READ_REPLICA: "read_replicas",
        OperationKind.STORAGE: "storage",
        OperationKind.OBSERVABILITY: "observability",
        OperationKind.ROLLBACK: "rollback",
        OperationKind.JOB: "last_job",
    }
    if kind is OperationKind.SCALE:
        next_desired["replicas"] = requested["replicas"]
    elif kind is OperationKind.SCHEDULE:
        schedules = list(next_desired.get("schedules", []))
        if requested not in schedules:
            schedules.append(deepcopy(requested))
        next_desired["schedules"] = schedules
    elif kind in mapping:
        next_desired[mapping[kind]] = deepcopy(requested)
    return next_desired


def list_operations(
    session: Session, service_id: uuid.UUID, *, owner_id: uuid.UUID | None = None
) -> list[ServiceOperation]:
    service = _require_service(session, service_id, owner_id=owner_id)
    rows = session.exec(
        select(ServiceOperation)
        .where(ServiceOperation.service_id == service.id)
        .order_by(ServiceOperation.created_at.desc(), ServiceOperation.id.desc())
    ).all()
    return list(rows)


def get_operations_state(
    session: Session, service_id: uuid.UUID, *, owner_id: uuid.UUID | None = None
) -> ServiceOperationsState:
    service = _require_service(session, service_id, owner_id=owner_id)
    state = _state_for(session, service)
    session.commit()
    session.refresh(state)
    return state


def create_operation(
    session: Session,
    *,
    service_id: uuid.UUID,
    kind: OperationKind,
    requested: dict[str, Any],
    idempotency_key: str,
    database_only: bool = False,
    owner_id: uuid.UUID | None = None,
) -> ServiceOperation:
    """Create audit history and update the desired aggregate in one transaction."""
    service = _require_service(session, service_id, owner_id=owner_id)
    if database_only:
        _require_database(service, kind)
    if kind in _APP_ONLY_KINDS:
        _require_app(service, kind)

    existing_key = session.exec(
        select(ServiceOperation).where(
            ServiceOperation.service_id == service.id,
            ServiceOperation.idempotency_key == idempotency_key,
        )
    ).first()
    if existing_key is not None:
        if existing_key.kind is kind and existing_key.requested == requested:
            return existing_key
        raise ConflictError(
            "Idempotency-Key was already used for a different service operation",
            details={"service_id": str(service.id), "idempotency_key": idempotency_key},
        )

    request_hash = _request_hash(
        service_id=service.id, kind=kind, requested=requested, key=idempotency_key
    )
    existing = session.exec(
        select(ServiceOperation).where(
            ServiceOperation.service_id == service.id,
            ServiceOperation.request_hash == request_hash,
        )
    ).first()
    if existing is not None:
        return existing

    operation = ServiceOperation(
        service_id=service.id,
        kind=kind,
        request_hash=request_hash,
        idempotency_key=idempotency_key,
        requested=requested,
    )
    state = _state_for(session, service)
    state.desired = _desired_after_operation(state.desired, kind, requested)
    _touch_pending(state)
    session.add_all((operation, state))
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        winner = session.exec(
            select(ServiceOperation).where(
                ServiceOperation.service_id == service.id,
                ServiceOperation.idempotency_key == idempotency_key,
            )
        ).first()
        if winner is not None and winner.kind is kind and winner.requested == requested:
            return winner
        raise ConflictError(
            "operation request conflicted with existing state",
            details={"service_id": str(service.id), "kind": kind.value},
        ) from exc
    session.refresh(operation)
    return operation


def update_operations_intent(
    session: Session,
    *,
    service_id: uuid.UUID,
    owner_id: uuid.UUID,
    changes: dict[str, Any],
    expected_version: int,
) -> ServiceOperationsState:
    """Deep-merge validated desired state and retain an immutable configuration audit row."""
    service = _require_service(session, service_id, owner_id=owner_id)
    state = _state_for(session, service)
    if state.version != expected_version:
        raise ConflictError(
            "service operations state has changed; reload and retry",
            details={"expected_version": expected_version, "actual_version": state.version},
        )
    allowed = set(ServiceOperationsIntent.model_fields)
    unknown = set(changes) - allowed
    if unknown:
        raise InvalidRequestError(
            "unknown operations intent fields", details={"fields": sorted(unknown)}
        )
    if set(changes) & _APP_ONLY_INTENT_FIELDS:
        _require_app(service, OperationKind.CONFIGURE)
    if set(changes) & _DATABASE_ONLY_INTENT_FIELDS:
        _require_database(service, OperationKind.CONFIGURE)
    if (
        "replicas" in changes
        and service.kind is ServiceKind.DATABASE
        and _database_role(service) == "primary"
    ):
        raise InvalidRequestError(
            "manual scale cannot target database primaries",
            details={"service_id": str(service.id)},
        )
    merged = _deep_merge(state.desired, changes)
    try:
        normalized = ServiceOperationsIntent.model_validate(merged).model_dump(mode="json")
    except ValidationError as exc:
        raise InvalidRequestError(
            "operations intent failed validation", details={"errors": exc.errors()}
        ) from exc

    operation = ServiceOperation(
        service_id=service.id,
        kind=OperationKind.CONFIGURE,
        requested={"patch": changes, "from_version": state.version},
    )
    state.desired = normalized
    _touch_pending(state)
    session.add_all((operation, state))
    session.commit()
    session.refresh(state)
    return state


def delete_schedule(
    session: Session,
    *,
    service_id: uuid.UUID,
    operation_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> None:
    """Cancel a schedule without deleting its audit record."""
    service = _require_service(session, service_id, owner_id=owner_id)
    operation = session.get(ServiceOperation, operation_id)
    if (
        operation is None
        or operation.service_id != service.id
        or operation.kind is not OperationKind.SCHEDULE
    ):
        raise NotFoundError(
            f"schedule {operation_id} does not exist", details={"operation_id": str(operation_id)}
        )
    if operation.status is OperationStatus.CANCELLED:
        return
    state = _state_for(session, service)
    schedules = list(state.desired.get("schedules", []))
    try:
        schedules.remove(operation.requested)
    except ValueError:
        pass
    state.desired = {**state.desired, "schedules": schedules}
    _touch_pending(state)
    operation.status = OperationStatus.CANCELLED
    operation.observed = {**operation.observed, "cancelled": True}
    operation.completed_at = utc_now()
    session.add_all((operation, state))
    session.commit()
