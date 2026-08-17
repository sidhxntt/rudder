"""Ephemeral, one-time handoffs from a browser OAuth callback to the Rudder CLI.

The browser never receives a Rudder bearer token.  A CLI starts an opaque
handoff, GitHub returns to the normal server callback, and the CLI polls its
opaque id until it can consume the issued token exactly once.  These are
intentionally process-local: they are short lived and must not become a second
credential store.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


class InvalidCliHandoff(Exception):
    """The opaque id is unknown, expired, or has already been consumed."""


@dataclass(slots=True)
class _Handoff:
    expires_at: datetime
    token: str | None = None


class CliOAuthHandoffs:
    def __init__(self, *, ttl: timedelta = timedelta(minutes=5)) -> None:
        self._ttl = ttl
        self._records: dict[str, _Handoff] = {}

    def create(self) -> str:
        self._prune()
        handoff_id = secrets.token_urlsafe(32)
        self._records[handoff_id] = _Handoff(expires_at=datetime.now(UTC) + self._ttl)
        return handoff_id

    def complete(self, handoff_id: str, token: str) -> None:
        record = self._get(handoff_id)
        if record.token is not None:
            raise InvalidCliHandoff()
        record.token = token

    def consume(self, handoff_id: str) -> str | None:
        record = self._get(handoff_id)
        if record.token is None:
            return None
        token = record.token
        del self._records[handoff_id]
        return token

    def _get(self, handoff_id: str) -> _Handoff:
        self._prune()
        record = self._records.get(handoff_id)
        if record is None:
            raise InvalidCliHandoff()
        return record

    def _prune(self) -> None:
        now = datetime.now(UTC)
        for handoff_id, record in tuple(self._records.items()):
            if record.expires_at <= now:
                del self._records[handoff_id]
