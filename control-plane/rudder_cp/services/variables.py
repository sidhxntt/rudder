"""Variable encryption, storage, and reference resolution.

Three jobs, in dependency order:

1. **Encrypt at rest (D13).** Values are Fernet tokens, and specifically
   ``MultiFernet`` over ``RUDDER_SECRET_KEYS`` — a comma-separated list where the
   *first* key encrypts and every later key can still decrypt. That is the whole
   point: rotating the encryption key is prepending a new key to the env var and
   running :func:`rotate_service_variables`, not a data migration.
2. **Store.** Upsert/list/delete against the ``variable`` table. The plaintext
   never leaves this module — API schemas expose the key and the flags, never the
   value and never the ciphertext.
3. **Resolve (deploy path).** :func:`resolve_service_env` turns one service's
   variables into the ``dict[str, str]`` the container runtime is handed, chasing
   ``${{service.KEY}}`` references through sibling services.

No FastAPI imports here — this layer takes a ``Session`` and is tested directly.

Boot wiring note: call :func:`verify_secret_keys` from the FastAPI lifespan so a
misconfigured ``RUDDER_SECRET_KEYS`` fails at startup with an actionable message
instead of at the first deploy with a crypto traceback.
"""

from __future__ import annotations

import binascii
import re
import uuid
from dataclasses import dataclass
from functools import lru_cache

import sqlalchemy as sa
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from sqlmodel import Session, select

from rudder_cp.config import get_settings
from rudder_cp.models.service import Service, Variable

# --- errors -------------------------------------------------------------------


class SecretKeyConfigError(RuntimeError):
    """``RUDDER_SECRET_KEYS`` is missing or malformed.

    Deliberately not a ``VariableError``: this is an operator misconfiguration,
    not a user-facing data problem, and it must not be swallowed into a 4xx.
    """


class VariableError(Exception):
    """Base for problems the caller can attribute to user data."""


class ServiceNotFoundError(VariableError):
    """The service a variable operation targets does not exist."""


class ReferenceResolutionError(VariableError):
    """A ``${{service.KEY}}`` reference could not be resolved.

    The message is user-facing verbatim — it lands in
    ``Deployment.error_message`` and is shown in the UI, so it always names the
    reference that failed.
    """


class DecryptionError(RuntimeError):
    """Stored ciphertext did not decrypt under any configured key."""


# --- key handling -------------------------------------------------------------

_GENERATE_HINT = (
    'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
)

_EMPTY_KEYS_MESSAGE = (
    "RUDDER_SECRET_KEYS is empty. Variable values are encrypted at rest and the "
    "control plane cannot start without a key. Set it to a comma-separated list "
    "of Fernet keys — the first key encrypts, the rest are kept so old ciphertext "
    "still decrypts during a rotation. Generate one with:\n    " + _GENERATE_HINT
)


@lru_cache(maxsize=8)
def build_fernet(keys: tuple[str, ...]) -> MultiFernet:
    """Build the MultiFernet for an explicit key list. Cached on the keys.

    Cached on the key tuple rather than on "the settings", so it can never go
    stale: different keys are a different cache entry.

    Raises SecretKeyConfigError when the list is empty or any key is not a valid
    Fernet key, with a message that says exactly what to set.
    """
    if not keys:
        raise SecretKeyConfigError(_EMPTY_KEYS_MESSAGE)

    fernets: list[Fernet] = []
    for position, key in enumerate(keys, start=1):
        try:
            fernets.append(Fernet(key))
        except (ValueError, TypeError, binascii.Error) as exc:
            raise SecretKeyConfigError(
                f"RUDDER_SECRET_KEYS entry #{position} is not a valid Fernet key "
                f"({exc}). A Fernet key is 32 random bytes, url-safe base64 "
                f"encoded, 44 characters ending in '='. Generate one with:\n"
                f"    {_GENERATE_HINT}"
            ) from exc
    return MultiFernet(fernets)


def get_fernet() -> MultiFernet:
    """The MultiFernet for the currently configured keys. First key encrypts."""
    return build_fernet(tuple(get_settings().fernet_keys))


def verify_secret_keys() -> None:
    """Fail loudly at boot if the keys are unusable. Call from the lifespan."""
    get_fernet()


def encrypt_value(plaintext: str) -> bytes:
    """Encrypt under the *primary* (first) key. Returns the Fernet token."""
    return get_fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_value(token: bytes) -> str:
    """Decrypt with any configured key, newest first."""
    try:
        return get_fernet().decrypt(token).decode("utf-8")
    except InvalidToken as exc:
        raise DecryptionError(
            "A variable failed to decrypt under every key in RUDDER_SECRET_KEYS. "
            "The key that encrypted it was most likely dropped from the list — "
            "add it back (it may sit anywhere after the first entry) and re-run "
            "the rotation."
        ) from exc


# --- reference syntax ---------------------------------------------------------

# `${{service.VAR_NAME}}`.
#
# Whitespace tolerance, chosen deliberately:
#   * the stored value is stripped first, so leading/trailing whitespace around
#     the whole reference is ignored;
#   * whitespace is allowed just inside the braces and on either side of the dot
#     — `${{ postgres . DATABASE_URL }}` parses;
#   * no whitespace *inside* a name.
# The value must be exactly one reference. `postgres://${{db.HOST}}/x` is a plain
# literal, not a reference: partial interpolation needs escaping rules and makes
# "is this value a secret or a template" ambiguous, and nothing in Phase 1 needs
# it. Adding it later is backwards compatible; removing it would not be.
#
# The service part accepts letters, digits and dashes. D9 restricts real service
# names to lowercase, but the PRD writes both `${{postgres.DATABASE_URL}}` and
# `${{Postgres.DATABASE_URL}}`, so lookup is case-insensitive on the service name
# (see _find_sibling). Variable keys stay case-sensitive — env vars are.
_REFERENCE_RE = re.compile(
    r"^\$\{\{\s*(?P<service>[A-Za-z0-9][A-Za-z0-9-]{0,31})\s*\.\s*"
    r"(?P<key>[A-Za-z_][A-Za-z0-9_]{0,254})\s*\}\}$"
)

# A value that opens with `${{` but does not parse. Caught so a typo produces a
# real error instead of being silently stored as a literal.
_REFERENCE_PREFIX_RE = re.compile(r"^\s*\$\{\{")

# Belt and braces behind the visited-set cycle check: a chain this long is a
# mistake even if it is acyclic.
MAX_REFERENCE_DEPTH = 16


@dataclass(frozen=True, slots=True)
class Reference:
    """A parsed ``${{service.KEY}}``."""

    service_name: str
    key: str

    def render(self) -> str:
        return f"${{{{{self.service_name}.{self.key}}}}}"


def parse_reference(value: str) -> Reference | None:
    """Parse a reference, or return None when the value is a plain literal."""
    match = _REFERENCE_RE.match(value.strip())
    if match is None:
        return None
    return Reference(service_name=match.group("service"), key=match.group("key"))


def is_reference(value: str) -> bool:
    """True when the whole value is a ``${{service.KEY}}`` reference."""
    return parse_reference(value) is not None


def looks_like_broken_reference(value: str) -> bool:
    """True for a value that starts ``${{`` but is not a valid reference."""
    return _REFERENCE_PREFIX_RE.match(value) is not None and not is_reference(value)


# --- storage ------------------------------------------------------------------


async def list_variables(session: Session, service_id: uuid.UUID) -> list[Variable]:
    """Every variable for one service, ordered by key. Values stay encrypted."""
    await _require_service(session, service_id)
    statement = select(Variable).where(Variable.service_id == service_id).order_by(Variable.key)
    return list(session.exec(statement).all())


async def set_variable(session: Session, service_id: uuid.UUID, key: str, value: str) -> Variable:
    """Create or replace one variable. Idempotent — same body twice, same row.

    ``is_reference`` is derived from the value, never taken from the client, so
    the flag and the plaintext can never disagree.
    """
    await _require_service(session, service_id)

    if looks_like_broken_reference(value):
        raise ReferenceResolutionError(
            f"{value.strip()!r} looks like a reference but is not valid syntax. "
            "The form is ${{service-name.VAR_NAME}}."
        )

    existing = _get_variable(session, service_id, key)
    variable = existing or Variable(service_id=service_id, key=key, value_encrypted=b"")
    variable.value_encrypted = encrypt_value(value)
    variable.is_reference = is_reference(value)

    session.add(variable)
    # The reference target is allowed not to exist yet, but once the target
    # does exist we reject cycles at write time.  Flush first so a newly-created
    # row participates in the graph; rollback leaves the prior value intact.
    session.flush()
    service = await _require_service(session, service_id)
    try:
        validate_no_reference_cycles(session, service.environment_id)
    except ReferenceResolutionError:
        session.rollback()
        raise
    session.commit()
    session.refresh(variable)
    return variable


async def delete_variable(session: Session, service_id: uuid.UUID, key: str) -> bool:
    """Delete one variable. Returns False when it was not there."""
    await _require_service(session, service_id)
    variable = _get_variable(session, service_id, key)
    if variable is None:
        return False
    session.delete(variable)
    session.commit()
    return True


async def rotate_service_variables(session: Session, service_id: uuid.UUID) -> int:
    """Re-encrypt a service's variables under the current primary key.

    This is the payoff of D13's MultiFernet. To rotate: generate a key, prepend
    it to ``RUDDER_SECRET_KEYS`` keeping the old one, restart, run this for every
    service, then drop the old key. Nothing is ever unreadable in between, and
    there is no migration.

    ``MultiFernet.rotate`` decrypts with whichever key works and re-encrypts with
    the first — the plaintext never leaves this process.
    """
    fernet = get_fernet()
    variables = await list_variables(session, service_id)
    for variable in variables:
        try:
            variable.value_encrypted = fernet.rotate(variable.value_encrypted)
        except InvalidToken as exc:
            raise DecryptionError(
                f"Variable {variable.key!r} on service {service_id} does not "
                "decrypt under any key in RUDDER_SECRET_KEYS, so it cannot be "
                "rotated. Add the retiring key back to the list."
            ) from exc
        session.add(variable)
    session.commit()
    return len(variables)


# --- resolution (the deploy path) ---------------------------------------------


async def resolve_service_env(session: Session, service_id: uuid.UUID) -> dict[str, str]:
    """Resolve one service's full env var map, ready for the container runtime.

    This is what the deploy path calls. Plain values are decrypted as-is;
    references are followed to a sibling service **in the same environment**.

    References resolve transitively: if ``api.DB`` points at ``shared.DB`` which
    points at ``postgres.DATABASE_URL``, the chain is followed to the literal.
    Chosen over one-hop because a one-hop rule is an arbitrary cliff — a user
    factoring shared config into its own service hits it immediately — and the
    only real hazard of transitivity, a loop, costs one visited-set to close.
    Every hop stays inside the environment, so transitivity never widens the
    blast radius.

    Raises ReferenceResolutionError with a user-facing message (it becomes
    ``Deployment.error_message``) when a reference names a service or key that
    does not exist, crosses an environment boundary, or loops.
    """
    service = await _require_service(session, service_id)
    resolved: dict[str, str] = {}

    for variable in await list_variables(session, service_id):
        plaintext = decrypt_value(variable.value_encrypted)
        if not variable.is_reference:
            resolved[variable.key] = plaintext
            continue
        resolved[variable.key] = _follow(session, service, variable.key, plaintext)

    return resolved


def _follow(session: Session, origin: Service, origin_key: str, value: str) -> str:
    """Walk a reference chain to a literal. Iterative, so it cannot blow a stack."""
    chain = [f"{origin.name}.{origin_key}"]
    seen: set[tuple[uuid.UUID, str]] = {(origin.id, origin_key)}

    current_service = origin
    current_value = value

    for _ in range(MAX_REFERENCE_DEPTH):
        reference = parse_reference(current_value)
        if reference is None:
            # Only reachable if a row is flagged is_reference but holds a value
            # that does not parse. set_variable derives the flag from the value,
            # so this means the row was written outside the API.
            raise ReferenceResolutionError(
                f"{_context(origin, origin_key)}: {' -> '.join(chain)} is marked "
                "as a reference but is not valid ${{service-name.VAR_NAME}} syntax."
            )

        target = _find_sibling(session, current_service, reference, origin, origin_key)
        target_variable = _get_variable(session, target.id, reference.key)
        if target_variable is None:
            raise ReferenceResolutionError(
                f"{_context(origin, origin_key)}: {reference.render()} — service "
                f"{target.name!r} has no variable named {reference.key!r}."
            )

        node = (target.id, reference.key)
        chain.append(f"{target.name}.{reference.key}")
        if node in seen:
            raise ReferenceResolutionError(
                f"{_context(origin, origin_key)}: reference cycle "
                f"{' -> '.join(chain)}. A variable cannot depend on itself, "
                "directly or through other services."
            )
        seen.add(node)

        current_service = target
        current_value = decrypt_value(target_variable.value_encrypted)
        if not target_variable.is_reference:
            return current_value

    raise ReferenceResolutionError(
        f"{_context(origin, origin_key)}: reference chain longer than "
        f"{MAX_REFERENCE_DEPTH} hops ({' -> '.join(chain)}). Point the variable "
        "at a literal value."
    )


def _find_sibling(
    session: Session,
    current: Service,
    reference: Reference,
    origin: Service,
    origin_key: str,
) -> Service:
    """Look up the referenced service inside `current`'s environment.

    An environment is an isolation boundary, so the lookup is scoped to
    ``current.environment_id`` and never widened. When the name only exists
    elsewhere we say so explicitly, because "no such service" would be a
    confusing thing to read while staring at a service that plainly exists.
    """
    statement = select(Service).where(
        Service.environment_id == current.environment_id,
        sa.func.lower(Service.name) == reference.service_name.lower(),
    )
    sibling = session.exec(statement).first()
    if sibling is not None:
        return sibling

    elsewhere = session.exec(
        select(Service).where(sa.func.lower(Service.name) == reference.service_name.lower())
    ).first()
    if elsewhere is not None:
        raise ReferenceResolutionError(
            f"{_context(origin, origin_key)}: {reference.render()} — a service "
            f"named {reference.service_name!r} exists, but in a different "
            "environment. References cannot cross environments; an environment "
            "is an isolation boundary. Create the service in this environment "
            "instead."
        )

    raise ReferenceResolutionError(
        f"{_context(origin, origin_key)}: {reference.render()} — no service named "
        f"{reference.service_name!r} in this environment."
    )


def _context(origin: Service, origin_key: str) -> str:
    return f"Cannot resolve variable {origin_key!r} on service {origin.name!r}"


def validate_no_reference_cycles(session: Session, environment_id: uuid.UUID) -> None:
    """Reject every resolvable reference loop in one environment.

    Missing services or keys deliberately add no edge: forward references are
    legal and remain deploy-time errors until they are defined.  A DFS gives a
    concise user-facing path once the last edge of a cycle is saved.
    """
    services = list(
        session.exec(select(Service).where(Service.environment_id == environment_id)).all()
    )
    service_by_name = {service.name.lower(): service for service in services}
    variables = list(
        session.exec(
            select(Variable).where(Variable.service_id.in_([service.id for service in services]))
        ).all()
    ) if services else []
    by_node = {(variable.service_id, variable.key): variable for variable in variables}

    edges: dict[tuple[uuid.UUID, str], tuple[uuid.UUID, str]] = {}
    for node, variable in by_node.items():
        if not variable.is_reference:
            continue
        reference = parse_reference(decrypt_value(variable.value_encrypted))
        target_service = service_by_name.get(reference.service_name.lower()) if reference else None
        target = (target_service.id, reference.key) if target_service and reference else None
        if target in by_node:
            edges[node] = target

    visiting: list[tuple[uuid.UUID, str]] = []
    visited: set[tuple[uuid.UUID, str]] = set()

    def label(node: tuple[uuid.UUID, str]) -> str:
        service = next(service for service in services if service.id == node[0])
        return f"{service.name}.{node[1]}"

    def visit(node: tuple[uuid.UUID, str]) -> None:
        if node in visiting:
            cycle = visiting[visiting.index(node) :] + [node]
            raise ReferenceResolutionError(
                f"reference cycle at save time: {' -> '.join(label(item) for item in cycle)}"
            )
        if node in visited:
            return
        visiting.append(node)
        target = edges.get(node)
        if target is not None:
            visit(target)
        visiting.pop()
        visited.add(node)

    for node in edges:
        visit(node)


# --- internals ----------------------------------------------------------------


async def _require_service(session: Session, service_id: uuid.UUID) -> Service:
    service = session.get(Service, service_id)
    if service is None:
        raise ServiceNotFoundError(f"No service with id {service_id}.")
    return service


def _get_variable(session: Session, service_id: uuid.UUID, key: str) -> Variable | None:
    statement = select(Variable).where(
        Variable.service_id == service_id,
        Variable.key == key,
    )
    return session.exec(statement).first()
