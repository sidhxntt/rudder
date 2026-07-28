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

from rudder_cp.models import OperationKind, Service, ServiceKind, ServiceOperation
from rudder_cp.schemas.common import ConflictError, InvalidRequestError, NotFoundError
from rudder_cp.schemas.operations import ScaleOperationRequest, ScaleRequest


def _require_service(session: Session, service_id: uuid.UUID) -> Service:
    service = session.get(Service, service_id)
    if service is None:
        raise NotFoundError(
            f"service {service_id} does not exist", details={"service_id": str(service_id)}
        )
    return service


def get_service(session: Session, service_id: uuid.UUID) -> Service:
    """Public service lookup for routers that need persisted service policy."""
    return _require_service(session, service_id)


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


def list_operations(session: Session, service_id: uuid.UUID) -> list[ServiceOperation]:
    service = _require_service(session, service_id)
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
) -> ServiceOperation:
    """Create or return an identical durable operation.

    The unique index is the final concurrency guard.  We check first for the
    ordinary retry path, then re-read after an IntegrityError if two callers
    race to write the same request.
    """
    service = _require_service(session, service_id)
    if database_only:
        _require_database(service, kind)

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
                ServiceOperation.request_hash == request_hash,
            )
        ).first()
        if winner is not None:
            return winner
        raise ConflictError(
            "operation request conflicted with existing state",
            details={"service_id": str(service.id), "kind": kind.value},
        ) from exc
    session.refresh(operation)
    return operation
