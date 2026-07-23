"""Shared boundary types: the uniform error envelope and its plumbing.

The PRD's API rules say errors are uniform ``{code, message, details}``. That is
implemented in three pieces:

1. ``RudderError`` and its subclasses — plain exceptions raised by ``services/``.
   They carry the envelope but know nothing about HTTP transport.
2. ``translate_errors()`` — a context manager routers wrap their single service
   call in. It turns a ``RudderError`` into an ``HTTPException`` whose ``detail``
   is the envelope.
3. ``install_error_handlers(app)`` — registers app-level handlers so the wire
   body is *exactly* ``{code, message, details}`` instead of FastAPI's default
   ``{"detail": ...}`` wrapper, and so Pydantic's 422s use the same shape.

FastAPI is imported lazily inside (2) and (3) on purpose: ``services/`` imports
the exception classes from this module, and the domain layer must not pull the
web framework in behind its back.
"""

from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterator
    from contextlib import AbstractContextManager

    from fastapi import FastAPI


class ErrorCode(StrEnum):
    """Machine-readable error codes. Clients switch on these, not on prose."""

    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    FORBIDDEN = "forbidden"
    INVALID_REQUEST = "invalid_request"
    VALIDATION_ERROR = "validation_error"
    EXHAUSTED = "exhausted"


class ErrorEnvelope(BaseModel):
    """The one error shape this API ever returns."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "code": "conflict",
                "message": "an environment named 'production' already exists in this project",
                "details": {"project_id": "6f1c...", "name": "production"},
            }
        }
    )

    code: str = Field(description="Stable machine-readable code, e.g. 'not_found'.")
    message: str = Field(description="Human-readable explanation. Safe to show to a user.")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Structured context for the error. Shape varies by code.",
    )


class RudderError(Exception):
    """Base for every error the domain layer raises deliberately.

    Subclasses fix the HTTP status and default code. Callers may override the
    code to something more specific than the family default.
    """

    status_code: int = 400
    default_code: ErrorCode = ErrorCode.INVALID_REQUEST

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code.value
        self.details: dict[str, Any] = details or {}

    def envelope(self) -> ErrorEnvelope:
        return ErrorEnvelope(code=self.code, message=self.message, details=self.details)


class NotFoundError(RudderError):
    status_code = 404
    default_code = ErrorCode.NOT_FOUND


class ConflictError(RudderError):
    """A uniqueness or state conflict — duplicate name, taken hostname."""

    status_code = 409
    default_code = ErrorCode.CONFLICT


class ForbiddenError(RudderError):
    """Understood, well-formed, and refused on policy grounds."""

    status_code = 403
    default_code = ErrorCode.FORBIDDEN


class InvalidRequestError(RudderError):
    """Well-formed JSON whose meaning is wrong — a cross-field or cross-row rule."""

    status_code = 422
    default_code = ErrorCode.INVALID_REQUEST


class ResourceExhaustedError(RudderError):
    """A server-owned allocation pool ran dry (e.g. WireGuard subnets)."""

    status_code = 409
    default_code = ErrorCode.EXHAUSTED


_ERROR_DESCRIPTIONS: dict[int, str] = {
    403: "Refused on policy grounds",
    404: "Resource does not exist",
    409: "Conflicts with existing state",
    422: "Request failed validation",
}


def error_responses(*status_codes: int) -> dict[int | str, dict[str, Any]]:
    """OpenAPI ``responses=`` entries so generated SDKs get typed error models."""
    return {
        code: {
            "model": ErrorEnvelope,
            "description": _ERROR_DESCRIPTIONS.get(code, "Error"),
        }
        for code in status_codes
    }


def translate_errors() -> "AbstractContextManager[None]":
    """Turn domain errors into HTTP errors carrying the uniform envelope.

    Routers wrap their one service call in this. It is the only place in a
    router where an error is shaped.
    """
    from contextlib import contextmanager

    from fastapi import HTTPException

    @contextmanager
    def _cm() -> "Iterator[None]":
        try:
            yield
        except RudderError as err:
            raise HTTPException(
                status_code=err.status_code,
                detail=err.envelope().model_dump(),
            ) from err

    return _cm()


def install_error_handlers(app: "FastAPI") -> None:
    """Flatten every error body to ``{code, message, details}``.

    Without this the bodies are still uniform but nested one level under
    ``detail``. Call it once on the app, next to ``include_router``.
    """
    from fastapi import Request
    from fastapi.encoders import jsonable_encoder
    from fastapi.exceptions import RequestValidationError
    from fastapi.responses import JSONResponse
    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(RudderError)
    async def _handle_domain_error(_: Request, exc: RudderError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder(exc.envelope().model_dump()),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and {"code", "message"} <= set(detail):
            body = detail
        else:
            body = ErrorEnvelope(
                code=f"http_{exc.status_code}",
                message=str(detail),
            ).model_dump()
        return JSONResponse(
            status_code=exc.status_code,
            content=jsonable_encoder(body),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        body = ErrorEnvelope(
            code=ErrorCode.VALIDATION_ERROR.value,
            message="request validation failed",
            details={"errors": jsonable_encoder(exc.errors())},
        )
        return JSONResponse(status_code=422, content=jsonable_encoder(body.model_dump()))
