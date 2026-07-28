"""Persist service-operation intent without mutating the runtime inline.

The API records an immutable, idempotent request.  A later reconciler turns
that request into Kubernetes resources; keeping that work out of this module
means retries are safe and audit history survives control-plane restarts.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from rudder_cp.models import (
    Environment,
    OperationKind,
    Project,
    Service,
    ServiceKind,
    ServiceOperation,
)
from rudder_cp.schemas.common import ConflictError, InvalidRequestError, NotFoundError
from rudder_cp.schemas.operations import (
    ScaleOperationRequest,
    ScaleRequest,
    ServiceOperationsIntent,
)


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
        # Deliberately use 404 for a foreign service to avoid revealing that a
        # service UUID exists in another owner's environment.
        if project is None or project.owner_id != owner_id:
            raise NotFoundError(
                f"service {service_id} does not exist", details={"service_id": str(service_id)}
            )
    return service


def get_service(
    session: Session, service_id: uuid.UUID, *, owner_id: uuid.UUID | None = None
) -> Service:
    """Public service lookup for routers that need persisted service policy."""
    return _require_service(session, service_id, owner_id=owner_id)


def _request_hash(
    *, service_id: uuid.UUID, kind: OperationKind, requested: dict[str, Any], key: str
) -> str:
    """Hash every identity component so a reused header cannot cross-collide."""
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
    """Read the role from persisted service configuration, never the client."""
    role = service.build_config.get("data_role")
    return "read_replica" if role == "read_replica" else "primary"


def _require_database(service: Service, kind: OperationKind) -> None:
    if service.kind is not ServiceKind.DATABASE:
        raise InvalidRequestError(
            f"{kind.value} operations require a database service",
            details={"service_id": str(service.id), "service_kind": service.kind.value},
        )


def normalize_scale_request(service: Service, payload: ScaleOperationRequest) -> dict[str, Any]:
    """Use the database service record to apply the primary-scale policy."""
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
    """Create or return an identical durable operation.

    The unique index is the final concurrency guard.  We check first for the
    ordinary retry path, then re-read after an IntegrityError if two callers
    race to write the same request.
    """
    service = _require_service(session, service_id, owner_id=owner_id)
    if database_only:
        _require_database(service, kind)

    # An Idempotency-Key identifies one request for one service. Retrying the
    # exact request returns the durable record; changing either kind or body is
    # a client bug and must not silently enqueue a second mutation.
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
    session.add(operation)
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
        if winner is not None:
            if winner.kind is kind and winner.requested == requested:
                return winner
            raise ConflictError(
                "Idempotency-Key was already used for a different service operation",
                details={"service_id": str(service.id), "idempotency_key": idempotency_key},
            ) from exc
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
    intent: ServiceOperationsIntent,
) -> ServiceOperationsIntent:
    """Merge declared desired state into the service's durable configuration."""
    service = _require_service(session, service_id, owner_id=owner_id)
    current = service.build_config.get("operations", {})
    if not isinstance(current, dict):
        current = {}
    changes = intent.model_dump(exclude_unset=True, mode="json")
    merged = {**current, **changes}
    # Replace rather than mutate JSON in place so SQLAlchemy always marks the
    # column dirty on both PostgreSQL and SQLite test databases.
    service.build_config = {**service.build_config, "operations": merged}
    session.add(service)
    session.commit()
    session.refresh(service)
    return ServiceOperationsIntent.model_validate(service.build_config["operations"])


def delete_schedule(
    session: Session,
    *,
    service_id: uuid.UUID,
    operation_id: uuid.UUID,
    owner_id: uuid.UUID,
) -> None:
    """Remove a requested CronJob only when it belongs to the caller's service."""
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
    session.delete(operation)
    session.commit()
