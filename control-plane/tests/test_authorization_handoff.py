from datetime import timedelta

import pytest

from rudder_cp.services.authorization_handoff import (
    AuthorizationHandoffError,
    AuthorizationHandoffs,
)


def test_pending_authorization_returns_none_until_completed() -> None:
    handoffs = AuthorizationHandoffs()

    authorization_id = handoffs.create()

    assert handoffs.consume(authorization_id) is None


def test_completed_authorization_returns_token_once() -> None:
    handoffs = AuthorizationHandoffs()
    authorization_id = handoffs.create()

    handoffs.complete(authorization_id, "issued-token")

    assert handoffs.consume(authorization_id) == "issued-token"
    with pytest.raises(AuthorizationHandoffError, match="invalid, expired, or already consumed"):
        handoffs.consume(authorization_id)


def test_expired_authorization_is_rejected() -> None:
    handoffs = AuthorizationHandoffs(ttl=timedelta(seconds=-1))

    authorization_id = handoffs.create()

    with pytest.raises(AuthorizationHandoffError, match="invalid, expired, or already consumed"):
        handoffs.complete(authorization_id, "issued-token")
