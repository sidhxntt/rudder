"""Password hashing and JWT issue/verify.

Scope note: this module is *only* credentials. Variable encryption (Fernet /
MultiFernet, D13) lives in ``services/variables.py`` and must not be added here
— the PRD's repo-structure comment listing "JWT, password hash, Fernet" on one
line describes the security concern, not a mandate to couple two unrelated key
lifecycles in one file.

No FastAPI imports: ``services/auth.py`` depends on this module, and services
never import ``fastapi``. Keeping it clean here is what stops an import cycle
between the service layer and the router that exposes ``get_current_user``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from uuid import UUID

import jwt
from passlib.context import CryptContext

from rudder_cp.config import get_settings

JWT_ALGORITHM = "HS256"

# Single scheme on purpose. `deprecated="auto"` means a future second scheme can
# be prepended and old hashes are then reported as needing a rehash for free.
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class InvalidToken(Exception):
    """A token was absent, malformed, expired, or signed with another key.

    Deliberately one exception for every failure mode. Callers turn this into a
    single generic 401 — telling a client *why* its token failed is free
    reconnaissance.
    """


class InsecureConfiguration(Exception):
    """Refusing to sign or verify with an unset secret."""


@dataclass(frozen=True, slots=True)
class IssuedToken:
    """A signed token plus the expiry metadata a client needs to schedule renewal."""

    token: str
    expires_at: datetime

    @property
    def expires_in(self) -> int:
        """Whole seconds until expiry, floored at zero."""
        delta = (self.expires_at - datetime.now(UTC)).total_seconds()
        return max(0, int(delta))


def hash_password(password: str) -> str:
    """Hash a plaintext password with bcrypt. Salt is generated per call."""
    return _pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Constant-time check of a password against a stored hash.

    Returns ``False`` rather than raising when the stored hash is unreadable —
    a corrupt row is an authentication failure, not a 500.
    """
    try:
        return _pwd_context.verify(password, password_hash)
    except ValueError:
        # passlib.exc.UnknownHashError and friends all subclass ValueError.
        return False


@lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    """A throwaway hash used to equalise timing when no user matches.

    Without this, "unknown email" returns in microseconds while "wrong
    password" pays for a bcrypt verify, and the difference enumerates accounts.
    Cached because generating it costs a full bcrypt round.
    """
    return hash_password("rudder-timing-equaliser")


def _jwt_secret() -> str:
    secret = get_settings().jwt_secret
    if not secret:
        raise InsecureConfiguration(
            "RUDDER_JWT_SECRET is empty. Set it before starting the control plane — "
            "an empty signing key means anyone can mint a valid token."
        )
    return secret


def issue_token(user_id: UUID, ttl_seconds: int | None = None) -> IssuedToken:
    """Sign a token for ``user_id``.

    ``ttl_seconds`` defaults to ``settings.jwt_ttl_seconds``; it is a parameter
    only so tests can mint an already-expired token without time travel.
    """
    settings = get_settings()
    ttl = settings.jwt_ttl_seconds if ttl_seconds is None else ttl_seconds
    issued_at = datetime.now(UTC)
    expires_at = issued_at + timedelta(seconds=ttl)
    payload: dict[str, object] = {
        "sub": str(user_id),
        "iat": int(issued_at.timestamp()),
        "exp": int(expires_at.timestamp()),
    }
    token = jwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)
    return IssuedToken(token=token, expires_at=expires_at)


def decode_token(token: str) -> UUID:
    """Verify signature and expiry, and return the subject user id.

    ``algorithms`` is pinned so a forged ``{"alg": "none"}`` header cannot
    bypass verification, and ``exp``/``sub`` are required so a token minted
    without them is rejected rather than treated as eternal.
    """
    if not token:
        raise InvalidToken("No token supplied")
    try:
        payload = jwt.decode(
            token,
            _jwt_secret(),
            algorithms=[JWT_ALGORITHM],
            options={"require": ["exp", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise InvalidToken("Token is not valid") from exc

    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise InvalidToken("Token subject is missing or not a string")
    try:
        return UUID(subject)
    except ValueError as exc:
        raise InvalidToken("Token subject is not a user id") from exc
