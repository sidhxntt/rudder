"""Phase 6 metric retention/downsampling contract."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlmodel import Session, SQLModel, create_engine, select

from rudder_cp.models import RuntimeMetric
from rudder_cp.services.metrics import (
    FIVE_MINUTE_SECONDS,
    MINUTE_SECONDS,
    RAW_SECONDS,
    compact_runtime_metrics,
)


def test_metrics_roll_up_and_expire_without_unbounded_raw_rows() -> None:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    instance_id = uuid4()
    now = datetime(2026, 8, 17, 12, 0, tzinfo=UTC)
    with Session(engine) as session:
        # Old raw samples become one-minute aggregates; anything older than
        # seven days disappears after it has had a chance to roll up.
        for offset in range(0, 60, 10):
            session.add(
                RuntimeMetric(
                    instance_id=instance_id,
                    captured_at=now - timedelta(hours=2) + timedelta(seconds=offset),
                    resolution_seconds=RAW_SECONDS,
                    cpu_percent=10 + offset,
                    memory_bytes=1000 + offset,
                )
            )
        session.add(
            RuntimeMetric(
                instance_id=instance_id,
                captured_at=now - timedelta(days=8),
                resolution_seconds=FIVE_MINUTE_SECONDS,
                cpu_percent=1,
                memory_bytes=1,
            )
        )
        session.commit()

        assert compact_runtime_metrics(session, now=now) >= 1
        remaining = session.exec(select(RuntimeMetric)).all()
    assert not [row for row in remaining if row.resolution_seconds == RAW_SECONDS]
    assert any(row.resolution_seconds == MINUTE_SECONDS for row in remaining)
    assert not [row for row in remaining if row.resolution_seconds == FIVE_MINUTE_SECONDS]
