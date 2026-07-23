"""Wire types for auth. Separate from the tables, per the PRD's FastAPI layout.

``UserRead`` exists precisely so ``User.password_hash`` can never leave the
process: the schema has no such field, so no route, no matter how it is written,
can serialise it.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ErrorBody(BaseModel):
    """The uniform error shape from the PRD's API design rules.

    Declared here because auth is the first workstream to need it. When a shared
    ``rudder_cp/errors.py`` appears, this moves there unchanged.
    """

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


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
    created_at: datetime
