"""Bounded on-disk runtime logs collected from Docker agents.

Each service has a 5 MiB active file and one 5 MiB archive.  That fixed 10
MiB cap is deliberate: a noisy workload must lose old logs, never consume the
control plane's memory or disk indefinitely.  The agent sends snapshots rather
than holding an HTTP stream open, so a container or control-plane restart is
ordinary recovery rather than a broken log session.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

from rudder_cp.config import get_settings
from rudder_cp.logs.store import DEFAULT_KEEPALIVE_INTERVAL, DEFAULT_POLL_INTERVAL, LogEvent

ACTIVE_BYTES = 5 * 1024 * 1024
ARCHIVE_BYTES = 5 * 1024 * 1024


class RuntimeLogNotFound(LookupError):
    """No runtime log has yet been collected for the service."""


class RuntimeLogStore:
    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def path_for(self, service_id: str | UUID) -> Path:
        normalized = UUID(str(service_id))
        root = self.root.resolve()
        path = (root / f"{normalized}.log").resolve()
        if not path.is_relative_to(root):  # UUID validation makes this defensive only.
            raise ValueError("runtime log path escaped root")
        return path

    def exists(self, service_id: str | UUID) -> bool:
        return self.path_for(service_id).is_file()

    async def append_snapshot(
        self, service_id: str | UUID, text: str, *, dropped_bytes: int = 0
    ) -> int:
        """Persist only the unseen suffix of a bounded agent snapshot.

        A repeated poll commonly returns the previous tail.  Prefix/suffix
        overlap avoids duplicating it without an in-memory cursor.  A bounded
        query window means the comparison itself stays bounded too.
        """
        return await asyncio.to_thread(
            self._append_snapshot, self.path_for(service_id), text, dropped_bytes
        )

    @staticmethod
    def _append_snapshot(path: Path, text: str, dropped_bytes: int) -> int:
        path.parent.mkdir(parents=True, exist_ok=True)
        previous = b""
        if path.is_file():
            with path.open("rb") as handle:
                handle.seek(0, 2)
                size = handle.tell()
                handle.seek(max(0, size - 65_536))
                previous = handle.read()
        incoming = text.encode("utf-8", errors="replace")
        overlap_limit = min(len(previous), len(incoming))
        overlap = 0
        for width in range(overlap_limit, 0, -1):
            if previous[-width:] == incoming[:width]:
                overlap = width
                break
        write = incoming[overlap:]
        if dropped_bytes:
            write = f"[rudder: agent dropped {dropped_bytes} log bytes]\n".encode() + write
        if not write:
            return 0
        # A malicious or misconfigured agent must not bypass rotation by
        # returning one giant response. Keep the newest bytes, which are the
        # useful portion of a tail, and make that loss explicit in the log.
        if len(write) > ACTIVE_BYTES:
            marker = b"[rudder: runtime snapshot exceeded local cap; older bytes dropped]\n"
            write = marker + write[-(ACTIVE_BYTES - len(marker)) :]
        if path.exists() and path.stat().st_size + len(write) > ACTIVE_BYTES:
            archive = path.with_suffix(".log.1")
            path.replace(archive)
            if archive.stat().st_size > ARCHIVE_BYTES:
                with archive.open("rb") as source:
                    source.seek(-ARCHIVE_BYTES, 2)
                    retained = source.read()
                archive.write_bytes(retained)
        with path.open("ab") as handle:
            handle.write(write)
        return len(write)

    async def tail(
        self,
        service_id: str | UUID,
        *,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        keepalive_interval: float = DEFAULT_KEEPALIVE_INTERVAL,
    ) -> AsyncIterator[LogEvent]:
        path = self.path_for(service_id)
        if not path.is_file():
            raise RuntimeLogNotFound(f"no runtime log for service {service_id}")
        handle = await asyncio.to_thread(path.open, "r", encoding="utf-8", errors="replace")
        last_event_at = time.monotonic()
        try:
            while True:
                data = await asyncio.to_thread(handle.read)
                if data:
                    last_event_at = time.monotonic()
                    yield LogEvent("chunk", data)
                    continue
                now = time.monotonic()
                if now - last_event_at >= keepalive_interval:
                    last_event_at = now
                    yield LogEvent("keepalive", "")
                await asyncio.sleep(poll_interval)
        finally:
            await asyncio.to_thread(handle.close)


def get_runtime_log_store() -> RuntimeLogStore:
    return RuntimeLogStore(get_settings().runtime_log_dir)
