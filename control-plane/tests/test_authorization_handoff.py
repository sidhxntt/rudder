from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import rudder_cp.models  # noqa: F401 - register tables before metadata creation
from rudder_cp.models.authorization_handoff import AuthorizationHandoff
from rudder_cp.services.authorization_handoff import (
    AuthorizationHandoffError,
    AuthorizationHandoffs,
)


@pytest.fixture(name="sessions")
def sessions_fixture() -> Iterator[tuple[Session, Session]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as first, Session(engine) as second:
        yield first, second


def test_pending_authorization_is_visible_across_sessions(
    sessions: tuple[Session, Session],
) -> None:
    creator, consumer = sessions
    authorization_id = AuthorizationHandoffs(creator).create()

    assert AuthorizationHandoffs(consumer).consume(authorization_id) is None


def test_completed_authorization_returns_token_once_across_sessions(
    sessions: tuple[Session, Session],
) -> None:
    creator, consumer = sessions
    authorization_id = AuthorizationHandoffs(creator).create()

    AuthorizationHandoffs(consumer).complete(authorization_id, "issued-token")

    assert AuthorizationHandoffs(creator).consume(authorization_id) == "issued-token"
    with pytest.raises(AuthorizationHandoffError, match="invalid, expired, or already consumed"):
        AuthorizationHandoffs(consumer).consume(authorization_id)


def test_expired_authorization_is_rejected(
    sessions: tuple[Session, Session],
) -> None:
    creator, consumer = sessions
    authorization_id = AuthorizationHandoffs(creator, ttl=timedelta(seconds=-1)).create()

    with pytest.raises(AuthorizationHandoffError, match="invalid, expired, or already consumed"):
        AuthorizationHandoffs(consumer).complete(authorization_id, "issued-token")


def test_completed_then_expired_authorization_cannot_be_consumed(
    sessions: tuple[Session, Session],
) -> None:
    creator, consumer = sessions
    authorization_id = AuthorizationHandoffs(creator).create()
    AuthorizationHandoffs(consumer).complete(authorization_id, "issued-token")
    handoff = creator.get(AuthorizationHandoff, authorization_id)
    assert handoff is not None
    handoff.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    creator.add(handoff)
    creator.commit()

    with pytest.raises(AuthorizationHandoffError, match="invalid, expired, or already consumed"):
        AuthorizationHandoffs(consumer).consume(authorization_id)


def test_duplicate_completion_is_rejected(
    sessions: tuple[Session, Session],
) -> None:
    creator, consumer = sessions
    authorization_id = AuthorizationHandoffs(creator).create()
    AuthorizationHandoffs(consumer).complete(authorization_id, "issued-token")

    with pytest.raises(AuthorizationHandoffError, match="invalid, expired, or already consumed"):
        AuthorizationHandoffs(creator).complete(authorization_id, "replacement-token")
