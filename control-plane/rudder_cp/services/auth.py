"""Auth logic: seed the single user, check credentials, resolve a token.

Per the PRD's FastAPI layout this layer holds all the logic, takes ``Session``
as an argument, and never imports ``fastapi``. The router above it only maps the
exceptions raised here onto status codes.

There is no signup and no user CRUD. Both are explicit non-goals — the one user
comes from ``.env`` and is seeded on first boot.
"""

from __future__ import annotations

import logging
import secrets
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from rudder_cp.config import Settings, get_settings
from rudder_cp.models import User
from rudder_cp.security import (
    InvalidToken,
    IssuedToken,
    decode_token,
    dummy_password_hash,
    hash_password,
    issue_token,
    verify_password,
)

logger = logging.getLogger(__name__)

# The password Settings falls back to when RUDDER_ADMIN_PASSWORD is unset.
_PLACEHOLDER_PASSWORD = "change-me"


def _github_fallback_email(github_id: int) -> str:
    """Provide a non-deliverable address when GitHub does not disclose one."""
    return f"github-{github_id}@oauth.rudder.invalid"


class InvalidCredentials(Exception):
    """Email unknown or password wrong. The caller must not distinguish which."""


class SeedError(Exception):
    """The configured admin credentials cannot produce a usable user."""


async def seed_admin_user(session: Session, settings: Settings | None = None) -> User:
    """Create the single user from settings if the table is empty. Idempotent.

    Called from the FastAPI lifespan on every boot, so the important property is
    the negative one: if *any* user already exists this returns it untouched and
    never rewrites ``password_hash``. A restart must not silently reset the
    operator's password back to whatever ``.env`` happens to say — that would
    turn a stale env file into a credential rollback, and would also undo any
    password changed out of band.
    """
    settings = settings or get_settings()

    existing = session.exec(select(User)).first()
    if existing is not None:
        return existing

    if not settings.admin_email or not settings.admin_password:
        raise SeedError(
            "RUDDER_ADMIN_EMAIL and RUDDER_ADMIN_PASSWORD must both be set to seed the "
            "single user. There is no signup, so an unseeded install has no way in."
        )
    if settings.admin_password == _PLACEHOLDER_PASSWORD:
        logger.warning(
            "Seeding the admin user with the placeholder password. Set "
            "RUDDER_ADMIN_PASSWORD and change it via the API before exposing this host."
        )

    user = User(
        email=settings.admin_email,
        password_hash=hash_password(settings.admin_password),
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        # Two workers booting against one database raced us to the insert. The
        # other one won; its row is the truth and we leave it alone.
        session.rollback()
        winner = session.exec(select(User)).first()
        if winner is None:
            raise
        return winner

    session.refresh(user)
    logger.info("Seeded the single user %s", user.email)
    return user


async def find_or_create_github_user(
    session: Session,
    *,
    github_id: int,
    login: str,
    email: str | None,
) -> User:
    """Find a user by immutable GitHub ID, or create one for a first OAuth login.

    GitHub login names and emails may change, so only the numeric GitHub ID is
    used to link an existing account. A unique constraint makes the create path
    safe when two OAuth callbacks for a new user arrive concurrently.
    """
    user = session.exec(select(User).where(User.github_id == github_id)).first()
    if user is not None:
        user.github_login = login
        if email is not None:
            user.email = email
        session.commit()
        session.refresh(user)
        return user

    user = User(
        email=email or _github_fallback_email(github_id),
        password_hash=hash_password(secrets.token_urlsafe(48)),
        github_id=github_id,
        github_login=login,
    )
    session.add(user)
    try:
        session.commit()
    except IntegrityError:
        # Another callback may have inserted this GitHub identity first.
        session.rollback()
        winner = session.exec(select(User).where(User.github_id == github_id)).first()
        if winner is None:
            raise
        winner.github_login = login
        if email is not None:
            winner.email = email
        session.commit()
        session.refresh(winner)
        return winner

    session.refresh(user)
    return user


async def authenticate(session: Session, email: str, password: str) -> User:
    """Return the user for these credentials, or raise ``InvalidCredentials``.

    An unknown email still pays for one bcrypt verify against a throwaway hash.
    Without that, response time alone tells an attacker which addresses exist.
    """
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        verify_password(password, dummy_password_hash())
        raise InvalidCredentials("No user with that email")
    if not verify_password(password, user.password_hash):
        raise InvalidCredentials("Password does not match")
    return user


async def login(session: Session, email: str, password: str) -> tuple[User, IssuedToken]:
    """Authenticate and mint an access token. Raises ``InvalidCredentials``."""
    user = await authenticate(session, email, password)
    return user, issue_token(user.id)


async def user_for_token(session: Session, token: str) -> User:
    """Resolve a bearer token to its user. Raises ``InvalidToken``.

    A token whose signature and expiry are fine but whose subject no longer
    exists is treated as invalid, not as a 500 — that is what a token surviving
    a database reset looks like.
    """
    user_id: UUID = decode_token(token)
    user = session.get(User, user_id)
    if user is None:
        raise InvalidToken("Token subject is not a known user")
    return user
