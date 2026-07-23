"""Tests for Phase 1 step 3 — the single seeded user, JWT, and get_current_user.

SQLite in-memory throughout, built straight from SQLModel's metadata. Nothing
here needs Postgres: the auth path uses no Postgres-specific behaviour, and a
test suite that cannot run without a database container is a test suite that
stops being run.

Service-layer behaviour is tested against ``services/auth.py`` directly, per the
PRD's "tests hit this layer". The router tests only cover what the router
actually owns: status codes, the error envelope, and where the token comes from.
"""

from __future__ import annotations

from collections.abc import Iterator
from uuid import uuid4

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import rudder_cp.models  # noqa: F401  -- registers every table on the metadata
from rudder_cp.config import Settings, get_settings
from rudder_cp.db import get_session
from rudder_cp.models import User
from rudder_cp.routers import auth as auth_router
from rudder_cp.schemas.auth import UserRead
from rudder_cp.security import (
    InsecureConfiguration,
    InvalidToken,
    decode_token,
    hash_password,
    issue_token,
    verify_password,
)
from rudder_cp.services import auth as auth_service

ADMIN_EMAIL = "operator@rudder.test"
ADMIN_PASSWORD = "correct-horse-battery-staple"
# >= 32 bytes: pyjwt warns below that for HS256, and so should a real deployment.
JWT_SECRET = "test-signing-secret-at-least-32-bytes-long"


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the cached Settings at test values for the duration of one test."""
    monkeypatch.setenv("RUDDER_JWT_SECRET", JWT_SECRET)
    monkeypatch.setenv("RUDDER_JWT_TTL_SECONDS", "3600")
    monkeypatch.setenv("RUDDER_ADMIN_EMAIL", ADMIN_EMAIL)
    monkeypatch.setenv("RUDDER_ADMIN_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setenv("RUDDER_TLS_MODE", "off")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def session() -> Iterator[Session]:
    """A fresh in-memory database per test.

    StaticPool keeps every connection pointed at the same ``:memory:`` database;
    without it each checkout would get its own empty one.
    """
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


@pytest.fixture
def app(session: Session) -> FastAPI:
    """The auth router mounted the way main.py is expected to mount it."""
    app = FastAPI()
    app.include_router(auth_router.router)
    app.add_exception_handler(auth_router.ApiError, auth_router.api_error_handler)
    app.dependency_overrides[get_session] = lambda: session
    return app


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as client:
        yield client


@pytest.fixture
async def seeded_user(session: Session) -> User:
    return await auth_service.seed_admin_user(session)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def settings_with(email: str, password: str) -> Settings:
    return Settings(admin_email=email, admin_password=password)


def all_users(session: Session) -> list[User]:
    return list(session.exec(select(User)).all())


# --------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------


async def test_seed_creates_the_single_user_from_settings(session: Session) -> None:
    user = await auth_service.seed_admin_user(session)

    assert user.email == ADMIN_EMAIL
    assert user.id is not None
    assert verify_password(ADMIN_PASSWORD, user.password_hash)
    assert user.password_hash != ADMIN_PASSWORD
    assert len(all_users(session)) == 1


async def test_seed_is_idempotent_and_never_resets_an_existing_password(
    session: Session,
) -> None:
    """The property that matters: restarting the app must not reset credentials.

    A rotated password lives only in the database. If seeding overwrote it, a
    stale ``.env`` would silently roll the operator's credentials back on every
    boot.
    """
    first = await auth_service.seed_admin_user(session, settings_with(ADMIN_EMAIL, "original"))
    original_hash = first.password_hash

    second = await auth_service.seed_admin_user(session, settings_with(ADMIN_EMAIL, "different"))

    assert second.id == first.id
    assert second.password_hash == original_hash
    assert len(all_users(session)) == 1
    # The original password still works; the one from settings never took effect.
    assert await auth_service.authenticate(session, ADMIN_EMAIL, "original")
    with pytest.raises(auth_service.InvalidCredentials):
        await auth_service.authenticate(session, ADMIN_EMAIL, "different")


async def test_seed_does_not_add_a_second_user_when_the_email_changes(session: Session) -> None:
    """Single-tenant means one row, not one row per configured address."""
    await auth_service.seed_admin_user(session, settings_with("first@rudder.test", "pw-one"))
    await auth_service.seed_admin_user(session, settings_with("second@rudder.test", "pw-two"))

    users = all_users(session)
    assert len(users) == 1
    assert users[0].email == "first@rudder.test"


async def test_seed_refuses_empty_credentials(session: Session) -> None:
    with pytest.raises(auth_service.SeedError):
        await auth_service.seed_admin_user(session, settings_with(ADMIN_EMAIL, ""))
    assert all_users(session) == []


# --------------------------------------------------------------------------
# Service layer: credentials and tokens
# --------------------------------------------------------------------------


async def test_authenticate_accepts_the_seeded_credentials(
    session: Session, seeded_user: User
) -> None:
    user = await auth_service.authenticate(session, ADMIN_EMAIL, ADMIN_PASSWORD)
    assert user.id == seeded_user.id


async def test_authenticate_rejects_a_wrong_password(session: Session, seeded_user: User) -> None:
    with pytest.raises(auth_service.InvalidCredentials):
        await auth_service.authenticate(session, ADMIN_EMAIL, "not-the-password")


async def test_authenticate_rejects_an_unknown_email(session: Session, seeded_user: User) -> None:
    with pytest.raises(auth_service.InvalidCredentials):
        await auth_service.authenticate(session, "nobody@rudder.test", ADMIN_PASSWORD)


async def test_login_returns_a_token_that_resolves_to_the_user(
    session: Session, seeded_user: User
) -> None:
    user, issued = await auth_service.login(session, ADMIN_EMAIL, ADMIN_PASSWORD)

    assert user.id == seeded_user.id
    assert issued.expires_in > 0
    assert await auth_service.user_for_token(session, issued.token) == seeded_user


async def test_user_for_token_rejects_a_token_for_a_deleted_user(session: Session) -> None:
    issued = issue_token(uuid4())
    with pytest.raises(InvalidToken):
        await auth_service.user_for_token(session, issued.token)


# --------------------------------------------------------------------------
# security.py
# --------------------------------------------------------------------------


def test_password_hashing_is_salted_and_verifiable() -> None:
    one = hash_password("same-password")
    two = hash_password("same-password")

    assert one != two, "two hashes of one password must differ — bcrypt salts per call"
    assert verify_password("same-password", one)
    assert not verify_password("same-password ", one)


def test_verify_password_returns_false_for_a_corrupt_hash() -> None:
    assert verify_password("anything", "not-a-bcrypt-hash") is False


def test_token_round_trips_the_user_id() -> None:
    user_id = uuid4()
    assert decode_token(issue_token(user_id).token) == user_id


def test_expired_token_is_rejected() -> None:
    expired = issue_token(uuid4(), ttl_seconds=-10)
    with pytest.raises(InvalidToken):
        decode_token(expired.token)


def test_token_signed_with_another_key_is_rejected() -> None:
    other_secret = "a-completely-different-secret-of-adequate-length"
    forged = jwt.encode({"sub": str(uuid4()), "exp": 2**31}, other_secret, algorithm="HS256")
    with pytest.raises(InvalidToken):
        decode_token(forged)


def test_token_without_an_expiry_is_rejected() -> None:
    """An `alg: none` or exp-less token must not be treated as eternal."""
    eternal = jwt.encode({"sub": str(uuid4())}, JWT_SECRET, algorithm="HS256")
    with pytest.raises(InvalidToken):
        decode_token(eternal)


def test_malformed_and_empty_tokens_are_rejected() -> None:
    for bad in ("", "not-a-token", "a.b.c"):
        with pytest.raises(InvalidToken):
            decode_token(bad)


def test_an_unset_jwt_secret_refuses_to_sign(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RUDDER_JWT_SECRET", "")
    get_settings.cache_clear()
    with pytest.raises(InsecureConfiguration):
        issue_token(uuid4())


# --------------------------------------------------------------------------
# Router: login, get_current_user, error envelope
# --------------------------------------------------------------------------


def test_login_returns_a_usable_token(client: TestClient, seeded_user: User) -> None:
    response = client.post("/auth/token", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] > 0

    client.cookies.clear()  # prove the header alone is sufficient
    me = client.get("/auth/me", headers=bearer(body["access_token"]))
    assert me.status_code == 200
    assert me.json()["email"] == ADMIN_EMAIL


def test_get_current_user_returns_the_right_user(client: TestClient, seeded_user: User) -> None:
    token = issue_token(seeded_user.id).token
    client.cookies.clear()

    response = client.get("/auth/me", headers=bearer(token))

    assert response.status_code == 200
    assert response.json() == UserRead.model_validate(seeded_user).model_dump(mode="json")


def test_me_never_exposes_the_password_hash(client: TestClient, seeded_user: User) -> None:
    token = issue_token(seeded_user.id).token
    response = client.get("/auth/me", headers=bearer(token))

    assert set(response.json()) == {"id", "email", "created_at"}
    assert seeded_user.password_hash not in response.text


def test_wrong_password_is_a_generic_401(client: TestClient, seeded_user: User) -> None:
    response = client.post("/auth/token", json={"email": ADMIN_EMAIL, "password": "wrong"})

    assert response.status_code == 401
    body = response.json()
    assert set(body) == {"code", "message", "details"}
    assert body["code"] == "invalid_credentials"
    assert body["message"] == "Invalid email or password"
    assert body["details"] == {}


def test_a_bad_password_is_indistinguishable_from_an_unknown_email(
    client: TestClient, seeded_user: User
) -> None:
    """No account enumeration: both failures must be byte-identical."""
    wrong_password = client.post("/auth/token", json={"email": ADMIN_EMAIL, "password": "wrong"})
    unknown_email = client.post(
        "/auth/token", json={"email": "ghost@rudder.test", "password": ADMIN_PASSWORD}
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()
    assert "ghost@rudder.test" not in unknown_email.text


def test_absent_token_is_rejected(client: TestClient, seeded_user: User) -> None:
    response = client.get("/auth/me")

    assert response.status_code == 401
    assert response.json()["code"] == "not_authenticated"
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "header",
    [
        {"Authorization": "Bearer garbage"},
        {"Authorization": "Bearer "},
        {"Authorization": "Basic dXNlcjpwYXNz"},
        {"Authorization": "not-even-a-scheme"},
    ],
)
def test_malformed_authorization_headers_are_rejected(
    client: TestClient, seeded_user: User, header: dict[str, str]
) -> None:
    response = client.get("/auth/me", headers=header)

    assert response.status_code == 401
    assert set(response.json()) == {"code", "message", "details"}


def test_expired_token_is_rejected_by_the_endpoint(client: TestClient, seeded_user: User) -> None:
    expired = issue_token(seeded_user.id, ttl_seconds=-10).token

    response = client.get("/auth/me", headers=bearer(expired))

    assert response.status_code == 401
    assert response.json()["message"] == "Invalid or expired token"


# --------------------------------------------------------------------------
# The cookie half of the header-or-cookie decision
# --------------------------------------------------------------------------


def test_login_sets_an_httponly_samesite_cookie(client: TestClient, seeded_user: User) -> None:
    response = client.post("/auth/token", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})

    set_cookie = response.headers["set-cookie"]
    assert auth_router.SESSION_COOKIE in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie.replace("SameSite=Lax", "SameSite=lax")
    # TLS mode is off in dev, so a Secure cookie would never be sent back.
    assert "Secure" not in set_cookie


def test_the_cookie_alone_authenticates_the_browser(client: TestClient, seeded_user: User) -> None:
    client.post("/auth/token", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})

    response = client.get("/auth/me")  # no Authorization header, cookie jar only

    assert response.status_code == 200
    assert response.json()["email"] == ADMIN_EMAIL


def test_the_header_wins_over_a_stale_cookie(client: TestClient, seeded_user: User) -> None:
    client.cookies.set(auth_router.SESSION_COOKIE, "stale-and-invalid")
    token = issue_token(seeded_user.id).token

    response = client.get("/auth/me", headers=bearer(token))

    assert response.status_code == 200


def test_logout_clears_the_cookie(client: TestClient, seeded_user: User) -> None:
    client.post("/auth/token", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert client.get("/auth/me").status_code == 200

    logout = client.delete("/auth/token")

    assert logout.status_code == 204
    assert client.get("/auth/me").status_code == 401
