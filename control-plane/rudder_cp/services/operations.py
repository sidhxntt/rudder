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

import sqlalchemy as sa
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
    ServiceManagedCapabilities,
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
    OperationKind.SCHEDULE,
    OperationKind.JOB,
    OperationKind.ROLLBACK,
}

_APP_ONLY_INTENT_FIELDS = {"autoscaling", "placement", "rollout", "schedules"}
_DATABASE_ONLY_INTENT_FIELDS = {"backups", "restore", "read_replicas", "storage"}
_SQL_DATABASE_INTENT_FIELDS = {"backups", "restore", "read_replicas"}
_INTERNAL_ONLY_INTENT_FIELDS = {"rollback", "last_job", "schedules"}
_SQL_ENGINES = frozenset({"postgres", "mysql", "mariadb"})
_MAX_STATE_WRITE_RETRIES = 5


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
    # The one-row aggregate is lazily created because legacy services predate
    # operations.  A check-then-insert here is a production race: two first
    # requests can observe no row.  A nested transaction contains a unique
    # violation to its savepoint, then the winner is re-read in the outer
    # transaction rather than turning an otherwise valid request into a 500.
    candidate = ServiceOperationsState(service_id=service.id)
    try:
        with session.begin_nested():
            session.add(candidate)
            session.flush()
    except IntegrityError:
        state = session.exec(
            select(ServiceOperationsState).where(ServiceOperationsState.service_id == service.id)
        ).first()
        if state is not None:
            return state
        # A concurrent creator may not have committed yet.  The caller's
        # compare-and-swap retry will read it after that transaction resolves.
        raise
    return candidate


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


def _managed_capabilities(
    session: Session, service: Service
) -> ServiceManagedCapabilities | None:
    """Return trusted server-owned metadata, never browser build input."""
    return session.exec(
        select(ServiceManagedCapabilities).where(
            ServiceManagedCapabilities.service_id == service.id
        )
    ).first()


def get_managed_capabilities(
    session: Session, service_id: uuid.UUID, *, owner_id: uuid.UUID | None = None
) -> ServiceManagedCapabilities | None:
    """Return trusted capability metadata only after the normal owner check.

    Callers must project this result before returning it to a browser; raw job
    command allowlists are an execution policy, not user interface data.
    """

    service = _require_service(session, service_id, owner_id=owner_id)
    return _managed_capabilities(session, service)


def _database_role(capabilities: ServiceManagedCapabilities | None) -> str:
    is_replica = capabilities is not None and capabilities.data_role == "read_replica"
    return "read_replica" if is_replica else "primary"


def _require_database(service: Service, kind: OperationKind) -> None:
    if service.kind is not ServiceKind.DATABASE:
        raise InvalidRequestError(
            f"{kind.value} operations require a database service",
            details={"service_id": str(service.id), "service_kind": service.kind.value},
        )


def _require_sql_database(
    service: Service, kind: OperationKind, capabilities: ServiceManagedCapabilities | None
) -> None:
    _require_database(service, kind)
    engine = capabilities.database_engine if capabilities is not None else None
    if engine not in _SQL_ENGINES:
        raise InvalidRequestError(
            f"{kind.value} operations require a known compatible SQL engine",
            details={
                "service_id": str(service.id),
                "engine": engine or "unknown",
                "supported_engines": sorted(_SQL_ENGINES),
            },
        )


def _require_managed_database(
    service: Service, kind: OperationKind, capabilities: ServiceManagedCapabilities | None
) -> None:
    """Reject database mutations unless Rudder provisioned trusted metadata.

    A legacy or manually-created database service can still exist, but it
    cannot receive stateful operation intents until it is adopted through a
    server-controlled import/template path.  In particular, browser supplied
    ``build_config`` must never become an authorization signal.
    """
    _require_database(service, kind)
    if capabilities is None:
        raise InvalidRequestError(
            f"{kind.value} operations require managed database metadata",
            details={"service_id": str(service.id)},
        )


def _require_app(service: Service, kind: OperationKind) -> None:
    if service.kind is not ServiceKind.APP:
        raise InvalidRequestError(
            f"{kind.value} operations require an application service",
            details={"service_id": str(service.id), "service_kind": service.kind.value},
        )


def _require_allowed_job_command(
    service: Service,
    requested: dict[str, Any],
    capabilities: ServiceManagedCapabilities | None,
) -> None:
    """Allow execution only for commands explicitly stored in service metadata.

    The operation endpoint submits future runtime work; accepting arbitrary
    shell/process arguments here would turn a dashboard permission into
    remote-code execution.  Templates/imports may declare
    ``allowed_job_commands``.  Services without that persisted allowlist fail
    closed.
    """
    command = requested.get("command")
    if not isinstance(command, list) or not all(isinstance(part, str) for part in command):
        raise InvalidRequestError("job command must be a validated argument list")
    raw_allowlist = capabilities.allowed_job_commands if capabilities is not None else []
    allowed = {
        tuple(item)
        for item in raw_allowlist
        if isinstance(item, list) and all(isinstance(part, str) for part in item)
    } if isinstance(raw_allowlist, list) else set()
    if tuple(command) not in allowed:
        raise InvalidRequestError(
            "job command is not allowed by this service template",
            details={"service_id": str(service.id)},
        )


def normalize_scale_request(
    session: Session, service: Service, payload: ScaleOperationRequest
) -> dict[str, Any]:
    try:
        normalized = ScaleRequest(
            replicas=payload.replicas,
            service_kind=service.kind,
            data_role=_database_role(_managed_capabilities(session, service)),
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
    _require_app(service, OperationKind.ROLLBACK)
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


def _normalize_desired_intent(desired: dict[str, Any]) -> dict[str, Any]:
    """Validate the complete aggregate after every state transition."""
    try:
        return ServiceOperationsIntent.model_validate(desired).model_dump(mode="json")
    except ValidationError as exc:
        raise InvalidRequestError(
            "operations intent failed validation", details={"errors": exc.errors()}
        ) from exc


def _desired_after_operation(
    desired: dict[str, Any],
    kind: OperationKind,
    requested: dict[str, Any],
    *,
    operation_id: uuid.UUID,
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
        schedules.append(
            {
                "operation_id": str(operation_id),
                "spec": deepcopy(requested),
            }
        )
        next_desired["schedules"] = schedules
    elif kind is OperationKind.BACKUP:
        # Backups are transient actions, unlike storage/replica intent. Keep
        # their audit identity in desired state so the Kubernetes runtime can
        # create exactly one CNPG Backup CRD and the reconciler can clear it
        # after observing completion.
        next_desired["backups"] = {**deepcopy(requested), "operation_id": str(operation_id)}
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
    """Create audit history and desired state atomically, retrying CAS races.

    A deployment dashboard sees independent buttons (scale, resources, HPA,
    etc.), but they all update one desired-state aggregate.  The audit row and
    aggregate transition must commit together; otherwise two simultaneous
    buttons can retain both history records while silently dropping one intent.
    """
    for attempt in range(_MAX_STATE_WRITE_RETRIES):
        service = _require_service(session, service_id, owner_id=owner_id)
        capabilities = _managed_capabilities(session, service)
        if database_only:
            _require_managed_database(service, kind, capabilities)
        if kind in {OperationKind.BACKUP, OperationKind.RESTORE, OperationKind.READ_REPLICA}:
            _require_sql_database(service, kind, capabilities)
        if kind in _APP_ONLY_KINDS:
            _require_app(service, kind)
        if kind in {OperationKind.JOB, OperationKind.SCHEDULE}:
            _require_allowed_job_command(service, requested, capabilities)

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

        try:
            state = _state_for(session, service)
        except IntegrityError as exc:
            session.rollback()
            if attempt + 1 < _MAX_STATE_WRITE_RETRIES:
                continue
            raise ConflictError(
                "service operations state is being initialized; retry the request",
                details={"service_id": str(service.id)},
            ) from exc

        operation = ServiceOperation(
            service_id=service.id,
            kind=kind,
            request_hash=request_hash,
            idempotency_key=idempotency_key,
            requested=requested,
        )
        desired = _normalize_desired_intent(
            _desired_after_operation(
                state.desired,
                kind,
                requested,
                operation_id=operation.id,
            )
        )
        next_version = state.version + 1
        next_observed = {
            **state.observed,
            "reconciliation": {
                "pending": True,
                "requested_version": next_version,
            },
        }
        session.add(operation)
        try:
            # Flush the audit first. A duplicate idempotency key is then
            # handled below without ever publishing a desired-state update.
            session.flush()
            updated = session.execute(
                sa.update(ServiceOperationsState)
                .where(
                    ServiceOperationsState.id == state.id,
                    ServiceOperationsState.version == state.version,
                )
                .values(
                    desired=desired,
                    observed=next_observed,
                    version=next_version,
                    pending_reconciliation=True,
                    updated_at=utc_now(),
                )
                .execution_options(synchronize_session=False)
            )
            if updated.rowcount != 1:
                session.rollback()
                continue
            session.commit()
            session.refresh(operation)
            return operation
        except IntegrityError as exc:
            session.rollback()
            winner = session.exec(
                select(ServiceOperation).where(
                    ServiceOperation.service_id == service_id,
                    ServiceOperation.idempotency_key == idempotency_key,
                )
            ).first()
            if winner is not None and winner.kind is kind and winner.requested == requested:
                return winner
            if attempt + 1 < _MAX_STATE_WRITE_RETRIES:
                continue
            raise ConflictError(
                "operation request conflicted with existing state",
                details={"service_id": str(service_id), "kind": kind.value},
            ) from exc

    raise ConflictError(
        "service operations state changed repeatedly; reload and retry",
        details={"service_id": str(service_id)},
    )


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
    capabilities = _managed_capabilities(session, service)
    state = _state_for(session, service)
    allowed = set(ServiceOperationsIntent.model_fields) - _INTERNAL_ONLY_INTENT_FIELDS
    unknown = set(changes) - allowed
    if unknown:
        raise InvalidRequestError(
            "unknown operations intent fields", details={"fields": sorted(unknown)}
        )
    protected = set(changes) & _INTERNAL_ONLY_INTENT_FIELDS
    if protected:
        raise InvalidRequestError(
            "internal operations intent fields must be changed through typed endpoints",
            details={"fields": sorted(protected)},
        )
    if set(changes) & _APP_ONLY_INTENT_FIELDS:
        _require_app(service, OperationKind.CONFIGURE)
    if set(changes) & _DATABASE_ONLY_INTENT_FIELDS:
        _require_managed_database(service, OperationKind.CONFIGURE, capabilities)
    if set(changes) & _SQL_DATABASE_INTENT_FIELDS:
        _require_sql_database(service, OperationKind.CONFIGURE, capabilities)
    if (
        "replicas" in changes
        and service.kind is ServiceKind.DATABASE
        and _database_role(capabilities) == "primary"
    ):
        raise InvalidRequestError(
            "manual scale cannot target database primaries",
            details={"service_id": str(service.id)},
        )
    merged = _deep_merge(state.desired, changes)
    normalized = _normalize_desired_intent(merged)

    next_version = expected_version + 1
    next_observed = {
        **state.observed,
        "reconciliation": {
            "pending": True,
            "requested_version": next_version,
        },
    }
    updated = session.execute(
        sa.update(ServiceOperationsState)
        .where(
            ServiceOperationsState.id == state.id,
            ServiceOperationsState.version == expected_version,
        )
        .values(
            desired=normalized,
            observed=next_observed,
            version=next_version,
            pending_reconciliation=True,
            updated_at=utc_now(),
        )
        .execution_options(synchronize_session=False)
    )
    if updated.rowcount != 1:
        session.rollback()
        raise ConflictError(
            "service operations state has changed; reload and retry",
            details={"expected_version": expected_version},
        )

    operation = ServiceOperation(
        service_id=service.id,
        kind=OperationKind.CONFIGURE,
        requested={"patch": changes, "from_version": expected_version},
    )
    session.add(operation)
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
    """Cancel a schedule without allowing a stale state write to erase intent.

    This mirrors ``create_operation``'s aggregate compare-and-swap.  A cancel
    is a desired-state mutation just like scale/resources; both the audit
    status and the state version must advance in the same transaction.
    """
    for attempt in range(_MAX_STATE_WRITE_RETRIES):
        service = _require_service(session, service_id, owner_id=owner_id)
        operation = session.get(ServiceOperation, operation_id)
        if (
            operation is None
            or operation.service_id != service.id
            or operation.kind is not OperationKind.SCHEDULE
        ):
            raise NotFoundError(
                f"schedule {operation_id} does not exist",
                details={"operation_id": str(operation_id)},
            )
        if operation.status is OperationStatus.CANCELLED:
            return
        try:
            state = _state_for(session, service)
        except IntegrityError as exc:
            session.rollback()
            if attempt + 1 < _MAX_STATE_WRITE_RETRIES:
                continue
            raise ConflictError(
                "service operations state is being initialized; retry the request",
                details={"service_id": str(service.id)},
            ) from exc

        schedules = [
            schedule
            for schedule in state.desired.get("schedules", [])
            if not (
                isinstance(schedule, dict)
                and schedule.get("operation_id") == str(operation.id)
            )
        ]
        desired = _normalize_desired_intent({**state.desired, "schedules": schedules})
        next_version = state.version + 1
        observed = {
            **state.observed,
            "reconciliation": {
                "pending": True,
                "requested_version": next_version,
            },
        }
        try:
            updated = session.execute(
                sa.update(ServiceOperationsState)
                .where(
                    ServiceOperationsState.id == state.id,
                    ServiceOperationsState.version == state.version,
                )
                .values(
                    desired=desired,
                    observed=observed,
                    version=next_version,
                    pending_reconciliation=True,
                    updated_at=utc_now(),
                )
                .execution_options(synchronize_session=False)
            )
            if updated.rowcount != 1:
                session.rollback()
                continue
            session.execute(
                sa.update(ServiceOperation)
                .where(
                    ServiceOperation.id == operation.id,
                    ServiceOperation.status != OperationStatus.CANCELLED,
                )
                .values(
                    status=OperationStatus.CANCELLED,
                    observed={**operation.observed, "cancelled": True},
                    completed_at=utc_now(),
                )
                .execution_options(synchronize_session=False)
            )
            session.commit()
            return
        except IntegrityError as exc:
            session.rollback()
            if attempt + 1 < _MAX_STATE_WRITE_RETRIES:
                continue
            raise ConflictError(
                "schedule cancellation conflicted with service operations state",
                details={"service_id": str(service_id), "operation_id": str(operation_id)},
            ) from exc

    raise ConflictError(
        "service operations state changed repeatedly; reload and retry",
        details={"service_id": str(service_id)},
    )
