import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from rudder_cp.models.base import ServiceKind
from rudder_cp.models.operations import OperationKind, OperationStatus, ServiceOperation
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
    ScaleRequest,
    StorageResizeRequest,
)


def test_workload_operations_reject_database_manual_scale():
    with pytest.raises(ValidationError, match="database primaries"):
        ScaleRequest(replicas=3, service_kind=ServiceKind.DATABASE)


def test_data_operations_reject_pvc_shrink():
    with pytest.raises(ValidationError, match="cannot shrink"):
        StorageResizeRequest(current_size_mb=1024, requested_size_mb=512)


def test_operation_requests_define_typed_safe_defaults():
    assert ResourceRequest(cpu_request="250m", memory_limit_mb=1024).cpu_request == "250m"
    assert AutoscalingRequest(min_replicas=2, max_replicas=5).max_replicas == 5
    assert PlacementRequest(topology_spread=True, anti_affinity=True).topology_spread is True
    assert RolloutRequest(strategy="blue_green").strategy == "blue_green"
    assert RollbackRequest(deployment_id=uuid.uuid4()).deployment_id
    assert BackupRequest().retention_days == 7
    assert ReadReplicaRequest(replicas=1).public is False
    assert CronJobRequest(cron="0 * * * *", command=("python", "cleanup.py")).retries == 1
    assert OneOffJobRequest(command=("python", "manage.py", "migrate")).timeout_seconds == 900
    assert ObservabilityRequest(prometheus=True, grafana=True).grafana is True


@pytest.mark.parametrize("quantity", ["500m", "1", "0.5", "1e3"])
def test_resources_accept_kubernetes_cpu_quantities(quantity: str):
    assert ResourceRequest(cpu_request=quantity).cpu_request == quantity


def test_resources_reject_invalid_or_inverted_limits():
    with pytest.raises(ValidationError, match="Kubernetes CPU quantity"):
        ResourceRequest(cpu_request="500Mi")
    with pytest.raises(ValidationError, match="Kubernetes CPU quantity"):
        ResourceRequest(cpu_request="1e3m")
    with pytest.raises(ValidationError, match="cpu_request cannot exceed cpu_limit"):
        ResourceRequest(cpu_request="2", cpu_limit="1500m")
    with pytest.raises(ValidationError, match="memory_request_mb cannot exceed memory_limit_mb"):
        ResourceRequest(memory_request_mb=1024, memory_limit_mb=512)


def test_operations_reject_unsafe_cross_field_combinations():
    with pytest.raises(ValidationError, match="min_replicas"):
        AutoscalingRequest(min_replicas=5, max_replicas=2)
    with pytest.raises(ValidationError, match="private"):
        ReadReplicaRequest(replicas=1, public=True)
    with pytest.raises(ValidationError, match="acknowledgement"):
        RestoreRequest(backup_id=uuid.uuid4())
    with pytest.raises(ValidationError, match="at least one argument"):
        OneOffJobRequest(command=())


def test_service_operation_is_typed_durable_audit_record():
    operation = ServiceOperation(
        service_id=uuid.uuid4(),
        kind=OperationKind.SCALE,
        requested={"replicas": 3},
    )

    assert operation.status is OperationStatus.PENDING
    assert operation.observed == {}
    assert operation.kind is OperationKind.SCALE


def test_request_hash_is_unique_per_service_but_audit_records_may_omit_it():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    service_id = uuid.uuid4()
    try:
        with Session(engine) as session:
            session.add(
                ServiceOperation(
                    service_id=service_id,
                    kind=OperationKind.SCALE,
                    request_hash="same-request",
                    requested={"replicas": 3},
                )
            )
            session.commit()
            session.add(
                ServiceOperation(
                    service_id=service_id,
                    kind=OperationKind.SCALE,
                    request_hash="same-request",
                    requested={"replicas": 3},
                )
            )
            with pytest.raises(IntegrityError):
                session.commit()
            session.rollback()
            session.add(
                ServiceOperation(
                    service_id=service_id,
                    kind=OperationKind.BACKUP,
                    requested={"retention_days": 7},
                )
            )
            session.commit()
    finally:
        SQLModel.metadata.drop_all(engine)
