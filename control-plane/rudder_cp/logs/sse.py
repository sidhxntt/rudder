"""SSE framing for build logs.

Wire format (text/event-stream):

    data: <line>\\n            one or more, one per line of a chunk
    \\n

    : keepalive\\n\\n           comment; keeps proxies from killing an idle stream

    event: end\\n
    data: succeeded\\n\\n       terminal; the stream closes right after

Framing only. All file access lives in ``store.py``.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

from rudder_cp.logs.store import (
    DEFAULT_KEEPALIVE_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    BuildLogStore,
    LogEvent,
)

SSE_MEDIA_TYPE = "text/event-stream"

# Proxies buffer text/event-stream by default; these turn that off.
SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
}


def frame(event: LogEvent) -> str:
    """Render one log event as an SSE frame."""
    if event.kind == "keepalive":
        return ": keepalive\n\n"
    if event.kind == "end":
        return f"event: end\ndata: {event.text}\n\n"
    body = "".join(f"data: {line}\n" for line in event.text.split("\n"))
    return f"{body}\n"


async def build_log_events(
    store: BuildLogStore,
    deployment_id: str | UUID,
    *,
    poll_interval: float = DEFAULT_POLL_INTERVAL,
    keepalive_interval: float = DEFAULT_KEEPALIVE_INTERVAL,
) -> AsyncIterator[str]:
    """Tail a build log as SSE frames.

    If the client disconnects, Starlette closes this generator; the ``finally``
    inside ``BuildLogStore.tail`` closes the file handle and nothing leaks. The
    build is untouched -- this path never signals the writer.
    """
    events = store.tail(
        deployment_id,
        poll_interval=poll_interval,
        keepalive_interval=keepalive_interval,
    )
    try:
        async for event in events:
            yield frame(event)
    finally:
        await events.aclose()
