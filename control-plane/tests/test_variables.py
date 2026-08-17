"""Variable encryption, storage, and reference resolution.

Three invariants are load-bearing and each gets a test that would actually fail
if it broke:

1. **D13 key rotation works without a migration.** A value encrypted under an old
   key still decrypts after a new primary key is prepended, and the rotation
   helper moves it onto the new key. Tested with two real generated keys, not a
   mock.
2. **The value is write-only.** No API response body contains the plaintext or
   the ciphertext.
3. **Reference resolution terminates.** Cycles are reported, not recursed into.

Runs against SQLite in-memory with the ``get_session`` dependency overridden;
there is no Postgres and no Docker daemon in this environment.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from cryptography.fernet import Fernet, InvalidToken
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from rudder_cp.config import get_settings
from rudder_cp.db import get_session
from rudder_cp.models import Environment, Project, Service, User, Variable
from rudder_cp.routers import variables as variables_router
from rudder_cp.services import variables as vars_service

KEY_OLD = Fernet.generate_key().decode()
KEY_NEW = Fernet.generate_key().decode()

SECRET = "postgres://rudder:hunter2@db.internal:5432/shop"


# --- fixtures -----------------------------------------------------------------


def use_keys(monkeypatch: pytest.MonkeyPatch, *keys: str) -> None:
    """Point the control plane at an explicit key list. First key encrypts."""
    monkeypatch.setenv("RUDDER_SECRET_KEYS", ",".join(keys))
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def default_keys(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Every test starts with one known key and leaves no cached Settings behind."""
    use_keys(monkeypatch, KEY_OLD)
    yield
    get_settings.cache_clear()


@pytest.fixture
def session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as open_session:
        yield open_session
    engine.dispose()


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    """The app under test, built here rather than imported from main.py."""
    app = FastAPI()
    app.include_router(variables_router.router)
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as test_client:
        yield test_client


def make_environment(session: Session, name: str = "production") -> Environment:
    user = User(email=f"{uuid.uuid4()}@example.com", password_hash="x")
    session.add(user)
    session.commit()
    project = Project(name="shop", owner_id=user.id)
    session.add(project)
    session.commit()
    environment = Environment(project_id=project.id, name=name)
    session.add(environment)
    session.commit()
    session.refresh(environment)
    return environment


def make_service(session: Session, environment: Environment, name: str) -> Service:
    service = Service(environment_id=environment.id, name=name)
    session.add(service)
    session.commit()
    session.refresh(service)
    return service


# --- encryption ---------------------------------------------------------------


def test_encrypt_decrypt_round_trip() -> None:
    token = vars_service.encrypt_value(SECRET)
    assert token != SECRET.encode()
    assert SECRET.encode() not in token
    assert vars_service.decrypt_value(token) == SECRET


def test_encryption_is_non_deterministic() -> None:
    """Fernet embeds a random IV, so the same value never yields the same token."""
    assert vars_service.encrypt_value(SECRET) != vars_service.encrypt_value(SECRET)


def test_old_key_still_decrypts_after_rotation(monkeypatch: pytest.MonkeyPatch) -> None:
    """The D13 payoff: prepend a new primary key, old ciphertext keeps working."""
    use_keys(monkeypatch, KEY_OLD)
    old_token = vars_service.encrypt_value(SECRET)

    use_keys(monkeypatch, KEY_NEW, KEY_OLD)
    assert vars_service.decrypt_value(old_token) == SECRET

    # ...and new writes go out under the new primary key, not the old one.
    new_token = vars_service.encrypt_value(SECRET)
    with pytest.raises(InvalidToken):
        vars_service.build_fernet((KEY_OLD,)).decrypt(new_token)
    assert vars_service.build_fernet((KEY_NEW,)).decrypt(new_token).decode() == SECRET


def test_decrypt_without_the_right_key_is_a_clear_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    use_keys(monkeypatch, KEY_OLD)
    token = vars_service.encrypt_value(SECRET)

    use_keys(monkeypatch, KEY_NEW)
    with pytest.raises(vars_service.DecryptionError, match="RUDDER_SECRET_KEYS"):
        vars_service.decrypt_value(token)


async def test_rotation_helper_reencrypts_under_the_new_primary(
    session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment = make_environment(session)
    service = make_service(session, environment, "api")

    use_keys(monkeypatch, KEY_OLD)
    await vars_service.set_variable(session, service.id, "DATABASE_URL", SECRET)
    await vars_service.set_variable(session, service.id, "LOG_LEVEL", "debug")

    use_keys(monkeypatch, KEY_NEW, KEY_OLD)
    rotated = await vars_service.rotate_service_variables(session, service.id)
    assert rotated == 2

    # Drop the old key entirely: everything must still decrypt, which is only
    # true if rotate() actually re-encrypted under the new primary.
    use_keys(monkeypatch, KEY_NEW)
    assert await vars_service.resolve_service_env(session, service.id) == {
        "DATABASE_URL": SECRET,
        "LOG_LEVEL": "debug",
    }


# --- misconfiguration ---------------------------------------------------------


def test_empty_secret_keys_fails_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    use_keys(monkeypatch)
    with pytest.raises(vars_service.SecretKeyConfigError) as caught:
        vars_service.verify_secret_keys()

    message = str(caught.value)
    assert "RUDDER_SECRET_KEYS" in message
    assert "Fernet.generate_key()" in message


def test_malformed_secret_key_names_the_bad_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    use_keys(monkeypatch, KEY_OLD, "not-a-fernet-key")
    with pytest.raises(vars_service.SecretKeyConfigError) as caught:
        vars_service.verify_secret_keys()

    message = str(caught.value)
    assert "entry #2" in message
    assert "RUDDER_SECRET_KEYS" in message


def test_whitespace_only_secret_keys_is_treated_as_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RUDDER_SECRET_KEYS", " , ")
    get_settings.cache_clear()
    with pytest.raises(vars_service.SecretKeyConfigError):
        vars_service.encrypt_value("anything")


# --- reference parsing --------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "${{postgres.DATABASE_URL}}",
        "${{ postgres.DATABASE_URL }}",
        "${{postgres . DATABASE_URL}}",
        "  ${{postgres.DATABASE_URL}}  ",
    ],
)
def test_reference_whitespace_tolerance(value: str) -> None:
    reference = vars_service.parse_reference(value)
    assert reference is not None
    assert (reference.service_name, reference.key) == ("postgres", "DATABASE_URL")


@pytest.mark.parametrize(
    "value",
    [
        "postgres://user:pw@host/db",
        "",
        # Partial interpolation is deliberately NOT a reference.
        "postgres://${{db.HOST}}:5432/shop",
        "${{postgres.DATABASE_URL}} ${{redis.URL}}",
        "$ {{postgres.DATABASE_URL}}",
    ],
)
def test_values_that_are_not_references(value: str) -> None:
    assert vars_service.parse_reference(value) is None


@pytest.mark.parametrize("value", ["${{postgres}}", "${{postgres.}}", "${{.KEY}}"])
def test_broken_reference_syntax_is_detected(value: str) -> None:
    assert vars_service.looks_like_broken_reference(value)


# --- storage ------------------------------------------------------------------


async def test_set_variable_derives_is_reference(session: Session) -> None:
    environment = make_environment(session)
    service = make_service(session, environment, "api")

    plain = await vars_service.set_variable(session, service.id, "LOG_LEVEL", "debug")
    reference = await vars_service.set_variable(
        session, service.id, "DATABASE_URL", "${{postgres.DATABASE_URL}}"
    )

    assert plain.is_reference is False
    assert reference.is_reference is True


async def test_set_variable_is_idempotent(session: Session) -> None:
    environment = make_environment(session)
    service = make_service(session, environment, "api")

    first = await vars_service.set_variable(session, service.id, "TOKEN", SECRET)
    second = await vars_service.set_variable(session, service.id, "TOKEN", SECRET)

    assert first.id == second.id
    assert len(await vars_service.list_variables(session, service.id)) == 1
    assert vars_service.decrypt_value(second.value_encrypted) == SECRET


async def test_set_variable_overwrites(session: Session) -> None:
    environment = make_environment(session)
    service = make_service(session, environment, "api")

    await vars_service.set_variable(session, service.id, "TOKEN", "old")
    updated = await vars_service.set_variable(session, service.id, "TOKEN", "new")

    assert vars_service.decrypt_value(updated.value_encrypted) == "new"


async def test_delete_variable(session: Session) -> None:
    environment = make_environment(session)
    service = make_service(session, environment, "api")
    await vars_service.set_variable(session, service.id, "TOKEN", SECRET)

    assert await vars_service.delete_variable(session, service.id, "TOKEN") is True
    assert await vars_service.delete_variable(session, service.id, "TOKEN") is False
    assert await vars_service.list_variables(session, service.id) == []


async def test_unknown_service_is_rejected(session: Session) -> None:
    with pytest.raises(vars_service.ServiceNotFoundError):
        await vars_service.set_variable(session, uuid.uuid4(), "TOKEN", SECRET)


# --- resolution ---------------------------------------------------------------


async def test_resolve_plain_and_reference_values(session: Session) -> None:
    environment = make_environment(session)
    api = make_service(session, environment, "api")
    postgres = make_service(session, environment, "postgres")

    await vars_service.set_variable(session, postgres.id, "DATABASE_URL", SECRET)
    await vars_service.set_variable(session, api.id, "DATABASE_URL", "${{postgres.DATABASE_URL}}")
    await vars_service.set_variable(session, api.id, "PORT", "8080")

    resolved = await vars_service.resolve_service_env(session, api.id)
    assert resolved == {"DATABASE_URL": SECRET, "PORT": "8080"}
    assert all(isinstance(value, str) for value in resolved.values())


async def test_resolve_is_transitive(session: Session) -> None:
    """a -> shared -> postgres resolves to the literal."""
    environment = make_environment(session)
    api = make_service(session, environment, "api")
    shared = make_service(session, environment, "shared")
    postgres = make_service(session, environment, "postgres")

    await vars_service.set_variable(session, postgres.id, "DATABASE_URL", SECRET)
    await vars_service.set_variable(
        session, shared.id, "DATABASE_URL", "${{postgres.DATABASE_URL}}"
    )
    await vars_service.set_variable(session, api.id, "DATABASE_URL", "${{shared.DATABASE_URL}}")

    assert await vars_service.resolve_service_env(session, api.id) == {"DATABASE_URL": SECRET}


async def test_reference_to_missing_service_is_a_clear_error(session: Session) -> None:
    environment = make_environment(session)
    api = make_service(session, environment, "api")
    await vars_service.set_variable(session, api.id, "DATABASE_URL", "${{postgres.DATABASE_URL}}")

    with pytest.raises(vars_service.ReferenceResolutionError) as caught:
        await vars_service.resolve_service_env(session, api.id)

    message = str(caught.value)
    assert "${{postgres.DATABASE_URL}}" in message
    assert "no service named 'postgres'" in message


async def test_reference_to_missing_key_is_a_clear_error(session: Session) -> None:
    environment = make_environment(session)
    api = make_service(session, environment, "api")
    postgres = make_service(session, environment, "postgres")
    await vars_service.set_variable(session, postgres.id, "SOMETHING_ELSE", "x")
    await vars_service.set_variable(session, api.id, "DATABASE_URL", "${{postgres.DATABASE_URL}}")

    with pytest.raises(vars_service.ReferenceResolutionError) as caught:
        await vars_service.resolve_service_env(session, api.id)

    message = str(caught.value)
    assert "${{postgres.DATABASE_URL}}" in message
    assert "no variable named 'DATABASE_URL'" in message


async def test_cross_environment_reference_is_refused(session: Session) -> None:
    production = make_environment(session, "production")
    staging = make_environment(session, "staging")
    api = make_service(session, staging, "api")
    postgres = make_service(session, production, "postgres")

    await vars_service.set_variable(session, postgres.id, "DATABASE_URL", SECRET)
    await vars_service.set_variable(session, api.id, "DATABASE_URL", "${{postgres.DATABASE_URL}}")

    with pytest.raises(vars_service.ReferenceResolutionError) as caught:
        await vars_service.resolve_service_env(session, api.id)

    assert "different environment" in str(caught.value)


async def test_self_reference_cycle_is_detected(session: Session) -> None:
    environment = make_environment(session)
    api = make_service(session, environment, "api")
    with pytest.raises(vars_service.ReferenceResolutionError, match="save time") as caught:
        await vars_service.set_variable(session, api.id, "LOOP", "${{api.LOOP}}")
    assert "api.LOOP -> api.LOOP" in str(caught.value)
    assert await vars_service.list_variables(session, api.id) == []


async def test_two_service_reference_cycle_is_detected(session: Session) -> None:
    """a.X -> b.Y -> a.X terminates with an error instead of hanging."""
    environment = make_environment(session)
    a = make_service(session, environment, "a")
    b = make_service(session, environment, "b")

    await vars_service.set_variable(session, a.id, "X", "${{b.Y}}")
    with pytest.raises(vars_service.ReferenceResolutionError) as caught:
        await vars_service.set_variable(session, b.id, "Y", "${{a.X}}")

    message = str(caught.value)
    assert "cycle" in message
    assert "a.X" in message and "b.Y" in message


async def test_reference_service_name_is_case_insensitive(session: Session) -> None:
    """The PRD writes both ${{postgres.…}} and ${{Postgres.…}}; both must work."""
    environment = make_environment(session)
    api = make_service(session, environment, "postgres")
    consumer = make_service(session, environment, "api")

    await vars_service.set_variable(session, api.id, "DATABASE_URL", SECRET)
    await vars_service.set_variable(
        session, consumer.id, "DATABASE_URL", "${{Postgres.DATABASE_URL}}"
    )

    assert await vars_service.resolve_service_env(session, consumer.id) == {"DATABASE_URL": SECRET}


async def test_deep_chain_is_bounded(session: Session) -> None:
    """An acyclic but absurd chain stops at MAX_REFERENCE_DEPTH."""
    environment = make_environment(session)
    services = [
        make_service(session, environment, f"s{index}")
        for index in range(vars_service.MAX_REFERENCE_DEPTH + 3)
    ]
    for index, service in enumerate(services[:-1]):
        await vars_service.set_variable(session, service.id, "V", f"${{{{s{index + 1}.V}}}}")
    await vars_service.set_variable(session, services[-1].id, "V", SECRET)

    with pytest.raises(vars_service.ReferenceResolutionError, match="longer than"):
        await vars_service.resolve_service_env(session, services[0].id)


# --- API ----------------------------------------------------------------------


def test_put_never_returns_the_value(client: TestClient, session: Session) -> None:
    environment = make_environment(session)
    service = make_service(session, environment, "api")

    response = client.put(f"/services/{service.id}/variables/DATABASE_URL", json={"value": SECRET})
    assert response.status_code == 200

    body = response.json()
    assert body["key"] == "DATABASE_URL"
    assert body["is_reference"] is False
    assert set(body) == {"id", "service_id", "key", "is_reference", "created_at"}

    stored = session.exec(
        Variable.__table__.select().where(Variable.service_id == service.id)
    ).first()
    ciphertext = stored.value_encrypted

    assert SECRET not in response.text
    assert "hunter2" not in response.text
    assert ciphertext.decode() not in response.text


def test_list_never_returns_the_value(client: TestClient, session: Session) -> None:
    environment = make_environment(session)
    service = make_service(session, environment, "api")
    client.put(f"/services/{service.id}/variables/DATABASE_URL", json={"value": SECRET})
    client.put(
        f"/services/{service.id}/variables/CACHE_URL",
        json={"value": "${{redis.URL}}"},
    )

    response = client.get(f"/services/{service.id}/variables")
    assert response.status_code == 200
    assert SECRET not in response.text
    assert "hunter2" not in response.text

    body = response.json()
    assert [item["key"] for item in body] == ["CACHE_URL", "DATABASE_URL"]
    assert [item["is_reference"] for item in body] == [True, False]
    for item in body:
        assert "value" not in item
        assert "value_encrypted" not in item


def test_put_is_idempotent(client: TestClient, session: Session) -> None:
    environment = make_environment(session)
    service = make_service(session, environment, "api")
    url = f"/services/{service.id}/variables/TOKEN"

    first = client.put(url, json={"value": SECRET})
    second = client.put(url, json={"value": SECRET})

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert len(client.get(f"/services/{service.id}/variables").json()) == 1


def test_delete_round_trip(client: TestClient, session: Session) -> None:
    environment = make_environment(session)
    service = make_service(session, environment, "api")
    url = f"/services/{service.id}/variables/TOKEN"
    client.put(url, json={"value": SECRET})

    assert client.delete(url).status_code == 204
    assert client.delete(url).status_code == 404
    assert client.get(f"/services/{service.id}/variables").json() == []


def test_unknown_service_returns_uniform_404(client: TestClient) -> None:
    response = client.get(f"/services/{uuid.uuid4()}/variables")
    assert response.status_code == 404
    detail = response.json()["detail"]
    assert detail["code"] == "service_not_found"
    assert detail["message"]
    assert "service_id" in detail["details"]


def test_broken_reference_is_rejected_at_write_time(client: TestClient, session: Session) -> None:
    environment = make_environment(session)
    service = make_service(session, environment, "api")

    response = client.put(
        f"/services/{service.id}/variables/DATABASE_URL", json={"value": "${{postgres}}"}
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_reference"


def test_invalid_key_is_rejected(client: TestClient, session: Session) -> None:
    environment = make_environment(session)
    service = make_service(session, environment, "api")
    response = client.put(f"/services/{service.id}/variables/1BAD-KEY", json={"value": "x"})
    assert response.status_code == 422


def test_extra_body_fields_are_rejected(client: TestClient, session: Session) -> None:
    """`is_reference` is derived, never asserted by the client."""
    environment = make_environment(session)
    service = make_service(session, environment, "api")
    response = client.put(
        f"/services/{service.id}/variables/TOKEN",
        json={"value": "x", "is_reference": True},
    )
    assert response.status_code == 422
