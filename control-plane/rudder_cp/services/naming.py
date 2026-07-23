"""D9 — name rules.

Service and environment names become DNS labels in
``{service}.{environment}.{base_domain}``, so they are constrained at the API
boundary rather than discovered to be invalid when Traefik or an ACME challenge
chokes on them.

The pattern lives here and is re-exported as Pydantic ``Annotated`` types so the
schemas enforce it. That is deliberate: a bad name must come back as a clean 422
from the request model, never as a 500 from a database or a DNS library.
"""

import re
from typing import Annotated, Final

from pydantic import BeforeValidator, StringConstraints

from rudder_cp.schemas.common import InvalidRequestError

# D9, verbatim from the PRD. Max total length 32: 1 + 30 + 1.
NAME_PATTERN: Final[str] = r"^[a-z0-9]([a-z0-9-]{0,30}[a-z0-9])?$"
NAME_MAX_LENGTH: Final[int] = 32
NAME_DESCRIPTION: Final[str] = (
    "Lowercase DNS label: a-z, 0-9 and hyphens, must start and end "
    "alphanumeric, 1-32 characters. This becomes a hostname label."
)

_NAME_RE: Final[re.Pattern[str]] = re.compile(NAME_PATTERN)

# A full hostname: dot-separated DNS labels. Deliberately stricter than RFC 1123
# in one way (lowercase only) so that hostname uniqueness is a plain string
# comparison and not a case-folding question.
HOSTNAME_PATTERN: Final[str] = (
    r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$"
)
HOSTNAME_MAX_LENGTH: Final[int] = 253
HOSTNAME_DESCRIPTION: Final[str] = (
    "Lowercase dot-separated DNS hostname, at most 253 characters. "
    "Normalised to lowercase on write."
)

_HOSTNAME_RE: Final[re.Pattern[str]] = re.compile(HOSTNAME_PATTERN)

#: Use this in request schemas for anything that becomes a hostname label.
ResourceName = Annotated[
    str,
    StringConstraints(min_length=1, max_length=NAME_MAX_LENGTH, pattern=NAME_PATTERN),
]

def normalise_hostname(value: str) -> str:
    """Trim and lowercase before validating.

    DNS is case-insensitive, but the unique index on ``domain.hostname`` is
    not. Normalising on the way in keeps "collides with an existing hostname"
    a plain string comparison instead of a case-folding question.
    """
    if isinstance(value, str):
        return value.strip().lower()
    return value


#: Use this in request schemas for a user-supplied full hostname.
Hostname = Annotated[
    str,
    BeforeValidator(normalise_hostname),
    StringConstraints(
        min_length=1,
        max_length=HOSTNAME_MAX_LENGTH,
        pattern=HOSTNAME_PATTERN,
    ),
]

#: Project names are not hostname components, so they get a looser rule.
ProjectName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=64)]


def is_valid_name(value: str) -> bool:
    return _NAME_RE.match(value) is not None


def is_valid_hostname(value: str) -> bool:
    return len(value) <= HOSTNAME_MAX_LENGTH and _HOSTNAME_RE.match(value) is not None


def validate_name(value: str, *, field: str) -> str:
    """Belt-and-braces check for callers that did not come through a schema.

    Raises ``InvalidRequestError`` (422), never lets a bad label reach the DB.
    """
    if not is_valid_name(value):
        raise InvalidRequestError(
            f"{field} must match {NAME_PATTERN}",
            details={"field": field, "value": value, "pattern": NAME_PATTERN},
        )
    return value


def system_hostname(service_name: str, environment_name: str, base_domain: str) -> str:
    """The D15 system hostname for a service: ``{service}.{env}.{base_domain}``.

    One function, one definition. Service create, service rename and environment
    rename all call this so the three paths cannot drift apart.
    """
    return f"{service_name}.{environment_name}.{base_domain}".lower()
