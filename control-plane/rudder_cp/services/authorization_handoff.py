"""Short-lived, one-time authorization handoffs for browser-based sign-in."""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


class AuthorizationHandoffError(Exception):
    """Raised when an authorization handoff can no longer be used."""


@dataclass(slots=True)
class _AuthorizationHandoff:
    expires_at: datetime
    token: str | None = None


class AuthorizationHandoffs:
    """Keep opaque authorization handoffs in memory until they are consumed."""

    def __init__(self, *, ttl: timedelta = timedelta(minutes=5)) -> None:
        self._ttl = ttl
        self._handoffs: dict[str, _AuthorizationHandoff] = {}

    def create(self) -> str:
        self._prune()
        authorization_id = secrets.token_urlsafe(32)
        while authorization_id in self._handoffs:
            authorization_id = secrets.token_urlsafe(32)
        self._handoffs[authorization_id] = _AuthorizationHandoff(
            expires_at=datetime.now(UTC) + self._ttl
        )
        return authorization_id

    def complete(self, authorization_id: str, token: str) -> None:
        self._prune()
        handoff = self._get_pending(authorization_id)
        handoff.token = token

    def consume(self, authorization_id: str) -> str | None:
        self._prune()
        handoff = self._handoffs.get(authorization_id)
        if handoff is None:
            raise AuthorizationHandoffError(
                "Authorization request is invalid, expired, or already consumed."
            )
        if handoff.token is None:
            return None
        del self._handoffs[authorization_id]
        return handoff.token

    def _get_pending(self, authorization_id: str) -> _AuthorizationHandoff:
        handoff = self._handoffs.get(authorization_id)
        if handoff is None or handoff.token is not None:
            raise AuthorizationHandoffError(
                "Authorization request is invalid, expired, or already consumed."
            )
        return handoff

    def _prune(self) -> None:
        now = datetime.now(UTC)
        expired = [
            authorization_id
            for authorization_id, handoff in self._handoffs.items()
            if handoff.expires_at <= now
        ]
        for authorization_id in expired:
            del self._handoffs[authorization_id]
