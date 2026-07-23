"""Request/response types for variables.

The reason schemas are separate from tables, stated once: ``Variable`` carries
``value_encrypted`` and the API must never return it. The value is **write-only**
— it goes in through :class:`VariableUpsert` and it never comes back out. Not the
plaintext, not the ciphertext. The UI masks variables and the CLI cannot read
them back; the only consumer of a decrypted value is the deploy path, in-process.

Anything added to :class:`VariableRead` later must survive that rule.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from rudder_cp.models.service import Variable
from rudder_cp.schemas.common import ErrorEnvelope

# Env var keys: POSIX-ish. Leading digit rejected because most shells cannot
# export it.
VARIABLE_KEY_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]{0,254}$"

# Fernet handles any size; this is a sanity bound on a request body, not a
# crypto limit.
MAX_VALUE_LENGTH = 65536


class VariableUpsert(BaseModel):
    """Body of ``PUT /services/{service_id}/variables/{key}``.

    Only the value. The key is in the path (that is what makes the PUT
    idempotent and addressable) and ``is_reference`` is derived from the value by
    the service layer, never asserted by the client.
    """

    model_config = ConfigDict(extra="forbid")

    value: str = Field(
        max_length=MAX_VALUE_LENGTH,
        description=(
            "Write-only. A literal value, or a reference of the form "
            "${{service-name.VAR_NAME}} resolved against a sibling service in "
            "the same environment at deploy time. Never returned by any endpoint."
        ),
        examples=["postgres://...", "${{postgres.DATABASE_URL}}"],
    )


class VariableRead(BaseModel):
    """A variable, minus its value. This is the entire public shape."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    service_id: uuid.UUID
    key: str
    is_reference: bool = Field(description="True when the value is a ${{service.VAR}} reference.")
    created_at: datetime

    @classmethod
    def from_model(cls, variable: Variable) -> VariableRead:
        """Project a table row onto the public shape, dropping the ciphertext."""
        return cls(
            id=variable.id,
            service_id=variable.service_id,
            key=variable.key,
            is_reference=variable.is_reference,
            created_at=variable.created_at,
        )


# The error shape lives in schemas/common.py as ErrorEnvelope. A second model
# named ErrorBody here collided with the one in schemas/auth.py: FastAPI emits
# both under the same schema title, and the SDK generator silently dropped the
# 404/422 responses from every variables operation rather than fail loudly.
ErrorBody = ErrorEnvelope
