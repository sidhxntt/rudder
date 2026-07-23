"""Following a build log.

``GET /deployments/{id}/build-log`` is ``text/event-stream``:

    data: <line>            one or more per frame, blank line terminates it
    : keepalive             comment, ignored
    event: end              terminal frame
    data: succeeded|failed

Two things this has to get right:

**The end event is about the build, not the deploy.** ``close_log`` is called by
the builder, so ``succeeded`` means the image was built and pushed. Starting the
container, polling the health check and writing the Traefik config all happen
after the stream closes. ``follow_deployment`` therefore keeps polling the
deployment until it reaches a terminal status, and only ``live`` is exit 0.

**The log does not exist yet when the deploy is queued.** The endpoint 404s
rather than hanging on a stream that will never produce anything, which is the
right server behaviour and means the client waits for the file to appear —
bounded, and with a clear message if it never does.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from uuid import UUID

from rudder_sdk.api.deployments import get_deployment
from rudder_sdk.models import DeploymentRead, DeploymentStatus

from .client import Api, CliError
from .render import err, out

TERMINAL = frozenset(
    {
        DeploymentStatus.LIVE,
        DeploymentStatus.FAILED,
        DeploymentStatus.SUPERSEDED,
    }
)

# How long to wait for the build log file to appear after queueing a deploy.
_LOG_WAIT_SECONDS = 120.0
# How long to wait for the deploy to settle after the build log ends.
_SETTLE_SECONDS = 300.0
_POLL_INTERVAL = 1.0


def _parse_events(lines: Iterator[str]) -> Iterator[tuple[str | None, str]]:
    """Yield ``(event_name, data)`` per SSE frame. Comments are dropped."""
    event: str | None = None
    data: list[str] = []
    for raw in lines:
        line = raw.rstrip("\r")
        if line == "":
            if data or event is not None:
                # The server frames a chunk as one `data:` per line of
                # `chunk.split("\n")`, so a chunk ending in a newline produces a
                # trailing empty field. Dropping one undoes exactly that and
                # keeps genuine blank lines inside the build output.
                if data and data[-1] == "":
                    data.pop()
                yield event, "\n".join(data)
            event, data = None, []
            continue
        if line.startswith(":"):
            continue
        if line.startswith("event:"):
            event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data.append(line[len("data:") :].removeprefix(" "))
    if data or event is not None:
        yield event, "\n".join(data)


def stream_build_log(api: Api, deployment_id: UUID) -> str | None:
    """Print a build log to stdout. Returns the ``end`` payload, if one arrived."""
    result: str | None = None
    with api.stream("GET", f"/deployments/{deployment_id}/build-log") as response:
        for event, data in _parse_events(response.iter_lines()):
            if event == "end":
                result = data.strip()
                break
            if data:
                out(data)
    return result


def wait_for_build_log(
    api: Api, deployment_id: UUID, *, timeout: float = _LOG_WAIT_SECONDS
) -> None:
    """Block until the log file exists, or explain why it never will."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            with api.stream("GET", f"/deployments/{deployment_id}/build-log"):
                return
        except CliError as exc:
            if exc.status != 404:
                raise
        deployment: DeploymentRead = api.call(get_deployment.sync_detailed, deployment_id)
        if deployment.status in TERMINAL and deployment.status is not DeploymentStatus.LIVE:
            reason = deployment.error_message or "no reason recorded"
            raise CliError(
                f"Deployment {deployment.status.value} before the build started: {reason}"
            )
        if time.monotonic() >= deadline:
            raise CliError(
                f"No build log after {timeout:.0f}s (deployment is {deployment.status.value}). "
                "The deploy worker may not be running."
            )
        time.sleep(_POLL_INTERVAL)


def wait_for_terminal(
    api: Api, deployment_id: UUID, *, timeout: float = _SETTLE_SECONDS
) -> DeploymentRead:
    deadline = time.monotonic() + timeout
    while True:
        deployment: DeploymentRead = api.call(get_deployment.sync_detailed, deployment_id)
        if deployment.status in TERMINAL:
            return deployment
        if time.monotonic() >= deadline:
            raise CliError(
                f"Deployment still {deployment.status.value} after {timeout:.0f}s. "
                f"Check `rudder status`."
            )
        time.sleep(_POLL_INTERVAL)


def follow_deployment(api: Api, deployment_id: UUID) -> DeploymentRead:
    """Stream the build, then wait for the deploy to settle. Never raises on a
    failed build — the caller reads ``status`` and picks the exit code."""
    wait_for_build_log(api, deployment_id)
    build_result = stream_build_log(api, deployment_id)
    if build_result == "failed":
        err("build failed")
        return wait_for_terminal(api, deployment_id)
    out("build succeeded — starting container, waiting for health check")
    return wait_for_terminal(api, deployment_id)
