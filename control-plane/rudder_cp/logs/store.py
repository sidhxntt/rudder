"""Build log file store.

Phase 1 step 5: build logs go to a file on disk. The SSE endpoint tails that
file. Nothing in the read path may reference, signal, or cancel the writer --
a client hanging up must never stop a build.

Layout is one file per deployment under ``settings.build_log_dir``:

    {build_log_dir}/{deployment_id}.log

The last line of a finished log is a terminal marker. Without it a reader has
no way to tell "the build is still running" from "the build ended" and the SSE
stream could never correctly terminate. The marker uses U+0004 (EOT), which
``append`` strips from build output so the sentinel is unambiguous.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Literal, NamedTuple
from uuid import UUID

from rudder_cp.config import get_settings

BuildStatus = Literal["succeeded", "failed"]

_SENTINEL = "\x04"
_MARKER_PREFIX = f"{_SENTINEL}rudder-build-end:"
_MARKER_SUFFIX = f"{_SENTINEL}\n"

DEFAULT_POLL_INTERVAL = 0.25
DEFAULT_KEEPALIVE_INTERVAL = 15.0


class InvalidDeploymentId(ValueError):
    """The deployment id is not a UUID and cannot be turned into a log path."""


class BuildLogNotFound(LookupError):
    """No build log file exists for this deployment."""


class LogEvent(NamedTuple):
    """One thing that happened while tailing a log.

    ``chunk``     -- ``text`` is log output.
    ``keepalive`` -- nothing new for a while; ``text`` is empty.
    ``end``       -- the terminal marker was reached; ``text`` is the status.
    """

    kind: Literal["chunk", "keepalive", "end"]
    text: str


def terminal_marker(status: str) -> str:
    """The exact bytes written to close a log. Exposed for tests."""
    return f"{_MARKER_PREFIX}{status}{_MARKER_SUFFIX}"


class BuildLogStore:
    """Append-only build logs on disk, plus a tailing reader.

    The write side is called by the build pipeline; the read side by the SSE
    router. They share nothing but the file.
    """

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    # -- paths ---------------------------------------------------------------

    def path_for(self, deployment_id: str | UUID) -> Path:
        """Map a deployment id to its log file.

        A deployment id is a UUID, but this validates rather than trusts: any
        value that is not a UUID is rejected, so no caller-supplied string can
        ever escape ``root``.
        """
        try:
            normalized = UUID(str(deployment_id))
        except (ValueError, TypeError, AttributeError) as exc:
            raise InvalidDeploymentId(f"not a UUID: {deployment_id!r}") from exc

        root = self.root.resolve()
        path = (root / f"{normalized}.log").resolve()
        if not path.is_relative_to(root):  # belt and braces; unreachable for a UUID
            raise InvalidDeploymentId(f"path escapes log dir: {deployment_id!r}")
        return path

    def exists(self, deployment_id: str | UUID) -> bool:
        return self.path_for(deployment_id).is_file()

    # -- write side (build pipeline) -----------------------------------------

    async def open_log(self, deployment_id: str | UUID) -> Path:
        """Create (or truncate) the log for a deployment. Returns its path."""
        path = self.path_for(deployment_id)
        await asyncio.to_thread(self._create, path)
        return path

    async def append(self, deployment_id: str | UUID, text: str) -> None:
        """Append build output. Safe to await from the deploy worker.

        The write happens on a thread so a slow disk cannot stall the event
        loop, and uses O_APPEND so interleaved writers cannot clobber each
        other.
        """
        if not text:
            return
        path = self.path_for(deployment_id)
        await asyncio.to_thread(self._append, path, text.replace(_SENTINEL, ""))

    async def close_log(self, deployment_id: str | UUID, status: BuildStatus) -> None:
        """Write the terminal marker. Readers stop cleanly once they see it."""
        path = self.path_for(deployment_id)
        await asyncio.to_thread(self._append, path, terminal_marker(status))

    async def snapshot(self, deployment_id: str | UUID) -> tuple[str, str | None]:
        """Read the current visible output once, without subscribing to appends."""
        path = self.path_for(deployment_id)
        if not path.is_file():
            raise BuildLogNotFound(f"no build log for deployment {deployment_id}")
        data = await asyncio.to_thread(path.read_text, encoding="utf-8", errors="replace")
        text, status, done = _consume(data)
        return text, status if done else None

    @staticmethod
    def _create(path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8"):
            pass

    @staticmethod
    def _append(path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(text)

    # -- read side (SSE) -----------------------------------------------------

    async def tail(
        self,
        deployment_id: str | UUID,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        keepalive_interval: float = DEFAULT_KEEPALIVE_INTERVAL,
    ) -> AsyncIterator[LogEvent]:
        """Yield a log from the beginning, then follow appends until it ends.

        Existing content comes out immediately, so a reader that attaches after
        the build finished gets the whole log and a clean ``end`` rather than
        hanging. A reader that attaches mid-build keeps receiving appends. All
        file I/O runs on a thread and idle time is an ``asyncio.sleep``, so the
        event loop is never blocked.

        Closing the generator (client disconnect) closes the file handle and
        returns. It does not touch the writer.
        """
        path = self.path_for(deployment_id)
        if not path.is_file():
            raise BuildLogNotFound(f"no build log for deployment {deployment_id}")

        handle = await asyncio.to_thread(path.open, "r", encoding="utf-8", errors="replace")
        buffer = ""
        last_event_at = time.monotonic()
        try:
            while True:
                data = await asyncio.to_thread(handle.read)
                if data:
                    buffer += data
                    text, status, done = _consume(buffer)
                    buffer = "" if done else buffer[len(text) :]
                    if text:
                        last_event_at = time.monotonic()
                        yield LogEvent("chunk", text)
                    if done:
                        yield LogEvent("end", status)
                        return
                    continue

                now = time.monotonic()
                if now - last_event_at >= keepalive_interval:
                    last_event_at = now
                    yield LogEvent("keepalive", "")
                await asyncio.sleep(poll_interval)
        finally:
            await asyncio.to_thread(handle.close)


def _consume(buffer: str) -> tuple[str, str, bool]:
    """Split buffered bytes into (emittable text, terminal status, finished).

    A partially written marker is held back rather than emitted, so the
    sentinel never leaks into the stream.
    """
    index = buffer.find(_SENTINEL)
    if index == -1:
        return buffer, "", False

    text = buffer[:index]
    rest = buffer[index:]
    end = rest.find(_MARKER_SUFFIX, len(_SENTINEL))
    if end == -1:
        # Marker still being written; emit what precedes it and wait.
        return text, "", False

    marker = rest[: end + len(_MARKER_SUFFIX)]
    status = "unknown"
    if marker.startswith(_MARKER_PREFIX):
        status = marker[len(_MARKER_PREFIX) : -len(_MARKER_SUFFIX)] or "unknown"
    return text, status, True


def get_build_log_store() -> BuildLogStore:
    """FastAPI dependency. Tests override this to point at a tmp_path."""
    return BuildLogStore(get_settings().build_log_dir)
