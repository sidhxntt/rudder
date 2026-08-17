"""Short-lived, one-time authorization handoffs for browser-based sign-in."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa
from sqlmodel import Session, select

from rudder_cp.models.authorization_handoff import AuthorizationHandoff


class AuthorizationHandoffError(Exception):
    """Raised when an authorization handoff can no longer be used."""


class AuthorizationHandoffs:
    """Persist opaque authorization handoffs until they are consumed."""

    def __init__(self, session: Session, *, ttl: timedelta = timedelta(minutes=5)) -> None:
        self._session = session
        self._ttl = ttl

    def create(self) -> str:
        self._prune()
        authorization_id = secrets.token_urlsafe(32)
        handoff = AuthorizationHandoff(
            id=authorization_id,
            expires_at=datetime.now(UTC) + self._ttl,
        )
        self._session.add(handoff)
        self._session.commit()
        return authorization_id

    def complete(self, authorization_id: str, token: str) -> None:
        self._prune()
        statement = (
            sa.update(AuthorizationHandoff)
            .execution_options(synchronize_session=False)
            .where(
                AuthorizationHandoff.id == authorization_id,
                AuthorizationHandoff.token.is_(None),
                AuthorizationHandoff.expires_at > datetime.now(UTC),
            )
            .values(token=token)
        )
        result = self._session.exec(statement)
        self._session.commit()
        if result.rowcount != 1:
            raise AuthorizationHandoffError(
                "Authorization request is invalid, expired, or already consumed."
            )

    def consume(self, authorization_id: str) -> str | None:
        self._prune()
        while True:
            statement = (
                sa.delete(AuthorizationHandoff)
                .execution_options(synchronize_session=False)
                .where(
                    AuthorizationHandoff.id == authorization_id,
                    AuthorizationHandoff.token.is_not(None),
                    AuthorizationHandoff.expires_at > datetime.now(UTC),
                )
                .returning(AuthorizationHandoff.token)
            )
            row = self._session.exec(statement).first()
            self._session.commit()
            token = row[0] if row is not None else None
            if token is not None:
                return token
            handoff = self._session.exec(
                select(AuthorizationHandoff).where(
                    AuthorizationHandoff.id == authorization_id,
                    AuthorizationHandoff.expires_at > datetime.now(UTC),
                )
            ).first()
            if handoff is None:
                raise AuthorizationHandoffError(
                    "Authorization request is invalid, expired, or already consumed."
                )
            if handoff.token is None:
                return None
            # Completion committed after the conditional DELETE. Retry so this
            # poll consumes the token instead of misreporting a valid handoff
            # as invalid. A concurrent consumer can only make the next pass
            # observe no row, which is correctly a one-time-use failure.
            continue

    def _prune(self) -> None:
        self._session.exec(
            sa.delete(AuthorizationHandoff)
            .execution_options(synchronize_session=False)
            .where(
                AuthorizationHandoff.expires_at <= datetime.now(UTC)
            )
        )
