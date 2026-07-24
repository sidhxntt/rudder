"""Uniform error shape for the agent HTTP API.

Per PRD "Interfaces" -> API design rules: errors are uniform `{code, message,
details}`. Every failure path in this process ends as an `AgentError` and is
serialized by the middleware in `main.py`.
"""

from typing import Any

from pydantic import BaseModel, Field


class ErrorBody(BaseModel):
    """The wire shape of every non-2xx response."""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class AgentError(Exception):
    """An expected failure with a known HTTP status and error code."""

    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details: dict[str, Any] = details or {}

    def body(self) -> ErrorBody:
        return ErrorBody(code=self.code, message=self.message, details=self.details)


def container_not_found(container_id: str) -> AgentError:
    return AgentError(
        404,
        "container_not_found",
        f"No container with id {container_id!r} on this host",
        {"container_id": container_id},
    )


def image_pull_failed(image: str, reason: str) -> AgentError:
    return AgentError(
        422,
        "image_pull_failed",
        f"Could not obtain image {image!r}: {reason}",
        {"image": image, "reason": reason},
    )


def name_conflict(name: str) -> AgentError:
    return AgentError(
        409,
        "container_name_in_use",
        f"A container named {name!r} already exists on this host",
        {"name": name},
    )


def docker_unavailable(reason: str) -> AgentError:
    return AgentError(
        503,
        "docker_unavailable",
        f"The Docker daemon is not reachable: {reason}",
        {"reason": reason},
    )


def docker_error(reason: str, details: dict[str, Any] | None = None) -> AgentError:
    return AgentError(502, "docker_error", f"Docker rejected the operation: {reason}", details)


def compose_error(reason: str) -> AgentError:
    return AgentError(502, "compose_error", f"Docker Compose failed: {reason}")


def invalid_request(message: str, details: dict[str, Any] | None = None) -> AgentError:
    return AgentError(400, "invalid_request", message, details)
