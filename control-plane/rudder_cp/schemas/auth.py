"""Wire types for auth. Separate from the tables, per the PRD's FastAPI layout.

``UserRead`` exists precisely so ``User.password_hash`` can never leave the
process: the schema has no such field, so no route, no matter how it is written,
can serialise it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from rudder_cp.schemas.common import ErrorEnvelope

# Now that schemas/common.py exists, that shared envelope IS the one error
# shape. Two models named ErrorBody (here and in schemas/variables.py) collided
# in the OpenAPI schema and broke SDK generation.
ErrorBody = ErrorEnvelope


class LoginRequest(BaseModel):
    """Credentials for ``POST /auth/token``.

    ``email`` is a plain ``str``, not ``EmailStr``: pydantic's email validator is
    a separate package that is not in ``pyproject.toml``, and there is exactly
    one user whose address came from ``.env`` — validating its format here would
    buy nothing and add a dependency.
    """

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=1)


class TokenResponse(BaseModel):
    """A freshly minted access token.

    ``expires_in`` is seconds from now, matching the OAuth 2.0 convention the
    CLI and both SDKs already expect from a bearer token response.
    """

    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class UserRead(BaseModel):
    """The single user, as the API sees them. Never carries ``password_hash``."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    github_login: str | None
    github_avatar_url: str | None
    created_at: datetime
