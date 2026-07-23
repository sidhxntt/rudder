"""Variables API — Phase 1 step 4.

# TODO(auth): protect with get_current_user — auth is a separate workstream and
# the dependency is wired in centrally at mount time.

Resource-oriented, sub-resource of a service, addressed by key:

    GET    /services/{service_id}/variables         list keys (never values)
    PUT    /services/{service_id}/variables/{key}   set — idempotent
    DELETE /services/{service_id}/variables/{key}   remove

**The value is write-only.** No endpoint in this file returns a plaintext or a
ciphertext, and none ever should.

``PUT`` returns 200 on both create and update rather than 201-then-200: "same
body twice, same result" is more useful to a CLI when the status code is part of
"the result".
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Response, status
from sqlmodel import Session

from rudder_cp.db import get_session
from rudder_cp.schemas.variables import (
    VARIABLE_KEY_PATTERN,
    ErrorBody,
    VariableRead,
    VariableUpsert,
)
from rudder_cp.services import variables as variables_service

router = APIRouter(prefix="/services/{service_id}/variables", tags=["variables"])

SessionDep = Annotated[Session, Depends(get_session)]
KeyPath = Annotated[
    str,
    Path(
        pattern=VARIABLE_KEY_PATTERN,
        description="Env var name, e.g. DATABASE_URL.",
    ),
]

_NOT_FOUND = {404: {"model": ErrorBody, "description": "No such service or variable"}}


def _error(status_code: int, code: str, message: str, **details: str) -> HTTPException:
    """Uniform error body per the PRD: {code, message, details}."""
    body = ErrorBody(code=code, message=message, details=details)
    return HTTPException(status_code=status_code, detail=body.model_dump())


@router.get(
    "",
    summary="List a service's variables",
    response_model=list[VariableRead],
    responses=_NOT_FOUND,
)
async def list_variables(service_id: UUID, session: SessionDep) -> list[VariableRead]:
    """Keys, reference flags and timestamps. Values are never returned."""
    try:
        rows = await variables_service.list_variables(session, service_id)
    except variables_service.ServiceNotFoundError as exc:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "service_not_found",
            str(exc),
            service_id=str(service_id),
        ) from exc
    return [VariableRead.from_model(row) for row in rows]


@router.put(
    "/{key}",
    summary="Set a variable (idempotent)",
    response_model=VariableRead,
    responses=_NOT_FOUND | {422: {"model": ErrorBody, "description": "Malformed value"}},
)
async def set_variable(
    service_id: UUID,
    key: KeyPath,
    body: VariableUpsert,
    session: SessionDep,
) -> VariableRead:
    """Create or replace one variable. The response omits the value by design."""
    try:
        variable = await variables_service.set_variable(session, service_id, key, body.value)
    except variables_service.ServiceNotFoundError as exc:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "service_not_found",
            str(exc),
            service_id=str(service_id),
        ) from exc
    except variables_service.ReferenceResolutionError as exc:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "invalid_reference",
            str(exc),
            key=key,
        ) from exc
    return VariableRead.from_model(variable)


@router.delete(
    "/{key}",
    summary="Delete a variable",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_NOT_FOUND,
)
async def delete_variable(service_id: UUID, key: KeyPath, session: SessionDep) -> Response:
    """204 when it is gone, 404 when it was never there."""
    try:
        deleted = await variables_service.delete_variable(session, service_id, key)
    except variables_service.ServiceNotFoundError as exc:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "service_not_found",
            str(exc),
            service_id=str(service_id),
        ) from exc
    if not deleted:
        raise _error(
            status.HTTP_404_NOT_FOUND,
            "variable_not_found",
            f"Service {service_id} has no variable named {key!r}.",
            key=key,
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
