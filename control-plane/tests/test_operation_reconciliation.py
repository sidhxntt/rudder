from sqlmodel import Session, SQLModel, create_engine

from rudder_cp.models import (
    Environment,
    OperationKind,
    OperationStatus,
    Project,
    Service,
    ServiceOperation,
    ServiceOperationsState,
    User,
)
from rudder_cp.services.operation_reconciler import (
    mark_runtime_operations_failed,
    mark_runtime_operations_progressing,
    reconcile_runtime_operations,
)


def test_runtime_reconciliation_marks_applied_and_unsupported_operations_truthfully() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(email="operations@example.com", password_hash="test")
        session.add(user)
        session.flush()
        project = Project(owner_id=user.id, name="shop")
        session.add(project)
        session.flush()
        environment = Environment(project_id=project.id, name="production")
        session.add(environment)
        session.flush()
        service = Service(environment_id=environment.id, name="worker")
        session.add(service)
        session.flush()
        state = ServiceOperationsState(
            service_id=service.id,
            desired={"replicas": 3, "read_replicas": {"replicas": 1}},
            pending_reconciliation=True,
            version=4,
        )
        scale = ServiceOperation(
            service_id=service.id,
            kind=OperationKind.SCALE,
            requested={"replicas": 3},
        )
        replica = ServiceOperation(
            service_id=service.id,
            kind=OperationKind.READ_REPLICA,
            requested={"replicas": 1, "public": False},
        )
        session.add_all([state, scale, replica])
        session.commit()

        started = mark_runtime_operations_progressing(session, service_ids=[service.id])
        session.refresh(scale)
        assert started == 2
        assert scale.status is OperationStatus.PROGRESSING

        outcome = reconcile_runtime_operations(
            session,
            service_id=service.id,
            runtime_observed={"rollout": {"status": "applied", "strategy": "rolling"}},
        )

        session.refresh(state)
        session.refresh(scale)
        session.refresh(replica)
        assert outcome == {"healthy": 1, "degraded": 1, "failed": 0}
        assert state.pending_reconciliation is False
        assert state.observed["reconciliation"]["status"] == "degraded"
        assert scale.status is OperationStatus.HEALTHY
        assert scale.observed["runtime"]["rollout"]["status"] == "applied"
        assert replica.status is OperationStatus.DEGRADED
        assert "database operator" in (replica.error_message or "")


def test_runtime_reconciliation_marks_started_operations_failed_when_release_fails() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        user = User(email="failed-operations@example.com", password_hash="test")
        session.add(user)
        session.flush()
        project = Project(owner_id=user.id, name="shop")
        session.add(project)
        session.flush()
        environment = Environment(project_id=project.id, name="production")
        session.add(environment)
        session.flush()
        service = Service(environment_id=environment.id, name="api")
        session.add(service)
        session.flush()
        state = ServiceOperationsState(
            service_id=service.id,
            desired={"replicas": 2},
            pending_reconciliation=True,
            version=2,
        )
        operation = ServiceOperation(
            service_id=service.id,
            kind=OperationKind.SCALE,
            requested={"replicas": 2},
        )
        session.add_all([state, operation])
        session.commit()

        mark_runtime_operations_progressing(session, service_ids=[service.id])
        failed = mark_runtime_operations_failed(
            session,
            service_ids=[service.id],
            reason="Kubernetes deployment did not become ready",
        )

        session.refresh(state)
        session.refresh(operation)
        assert failed == 1
        assert operation.status is OperationStatus.FAILED
        assert operation.error_message == "Kubernetes deployment did not become ready"
        assert state.pending_reconciliation is False
        assert state.observed["reconciliation"] == {
            "pending": False,
            "applied_version": 2,
            "status": "failed",
        }
