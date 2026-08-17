"""Auth logic: seed password access, link GitHub identities, resolve a token.

Per the PRD's FastAPI layout this layer holds all the logic, takes ``Session``
as an argument, and never imports ``fastapi``. The router above it only maps the
exceptions raised here onto status codes.

There is no signup or user CRUD. Password access is seeded from ``.env``;
GitHub OAuth access resolves returning users by GitHub's immutable numeric ID.
On a first login only, GitHub's verified primary email may link that identity
to an existing password-only local account.
"""

from __future__ import annotations

import logging
import secrets
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from rudder_cp.config import Settings, get_settings
from rudder_cp.models import Project, User
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
# A conflicted insert can be retried after a competing callback commits, but a
# persistent database constraint failure must reach the caller rather than spin.
GITHUB_USER_WRITE_ATTEMPTS = 3


def _canonical_github_email(email: str | None) -> str | None:
    """Canonicalize an optional GitHub email before it reaches a unique column."""
    if email is None:
        return None
    return email.strip().lower() or None


def _github_fallback_email(github_id: int, suffix: int = 0) -> str:
    """Return a deterministic, non-deliverable address for an OAuth identity."""
    tail = "" if suffix == 0 else f"-{suffix}"
    return f"github-{github_id}{tail}@oauth.rudder.invalid"


def _email_owner(session: Session, email: str) -> User | None:
    """Find the owner of an email under the same canonicalization policy."""
    return session.exec(
        select(User).where(func.lower(func.trim(User.email)) == email)
    ).first()


def _fallback_email(session: Session, github_id: int) -> str:
    """Choose a deterministic fallback that is unique among local accounts."""
    suffix = 0
    while True:
        candidate = _github_fallback_email(github_id, suffix)
        if _email_owner(session, candidate) is None:
            return candidate
        suffix += 1


class InvalidCredentials(Exception):
    """Email unknown or password wrong. The caller must not distinguish which."""


class SeedError(Exception):
    """The configured admin credentials cannot produce a usable user."""


async def seed_admin_user(session: Session, settings: Settings | None = None) -> User:
    """Create the configured password admin if no local user exists. Idempotent.

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
            "password admin. There is no signup, so an unseeded install has no way in."
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
    avatar_url: str | None = None,
) -> User:
    """Find a user by immutable GitHub ID, or create one for a first OAuth login.

    GitHub login names and emails may change, so only the numeric GitHub ID is
    used to find an existing OAuth identity. For a first OAuth login, the
    client supplies GitHub's verified primary email and can therefore attach
    that durable GitHub ID to a password-only account with the same email.
    New OAuth users use a deterministic non-deliverable fallback when there is
    no verified email to link.

    The unique GitHub-ID constraint makes concurrent first callbacks safe. If
    an insert races, the loop re-reads the winning identity; if only an email
    races, it re-evaluates the email policy and falls back without leaking an
    ``IntegrityError`` to the OAuth callback.
    """
    canonical_email = _canonical_github_email(email)
    last_error: IntegrityError | None = None

    for _ in range(GITHUB_USER_WRITE_ATTEMPTS):
        user = session.exec(select(User).where(User.github_id == github_id)).first()
        if user is not None:
            owner = _email_owner(session, canonical_email) if canonical_email else None
            if (
                owner is not None
                and owner.id != user.id
                and owner.github_id is None
                and user.email == _github_fallback_email(github_id)
            ):
                # Older OAuth callbacks could only see `/user`, so a private
                # GitHub email created this placeholder account. Once the
                # verified primary email is available, move its project graph
                # to the matching local account and retire the placeholder.
                projects = session.exec(select(Project).where(Project.owner_id == user.id)).all()
                for project in projects:
                    project.owner_id = owner.id
                session.delete(user)
                # `github_id` is unique. Flush the project reassignments and
                # deletion first so assigning that ID to the local account is
                # valid on databases that enforce uniqueness per statement.
                session.flush()
                owner.github_id = github_id
                owner.github_login = login
                owner.github_avatar_url = avatar_url
                user = owner
            else:
                user.github_login = login
                user.github_avatar_url = avatar_url
            if owner is None or owner.id == user.id:
                if canonical_email is not None:
                    user.email = canonical_email
        else:
            owner = _email_owner(session, canonical_email) if canonical_email else None
            if owner is not None and owner.github_id is None:
                owner.github_id = github_id
                owner.github_login = login
                owner.github_avatar_url = avatar_url
                user = owner
            else:
                user = User(
                    email=(
                        canonical_email
                        if canonical_email is not None and owner is None
                        else _fallback_email(session, github_id)
                    ),
                    password_hash=hash_password(secrets.token_urlsafe(48)),
                    github_id=github_id,
                    github_login=login,
                    github_avatar_url=avatar_url,
                )
                session.add(user)

        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            last_error = exc
            continue

        session.refresh(user)
        return user

    assert last_error is not None
    raise last_error


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
