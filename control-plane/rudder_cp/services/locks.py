"""Per-service deploy serialization. D11.

Two pushes two seconds apart must not produce two builds racing to write Traefik
config and two containers both claiming to be live.

On Postgres this is a session-level advisory lock held on a dedicated
connection for the length of the deploy. It is deliberately NOT a transaction
lock: a build takes minutes, and holding a transaction open that long pins a
snapshot and blocks vacuum for no benefit.

`try` semantics, not blocking: if another deploy for the service already holds
the lock, this one stays queued and the worker retries it on a later tick. A
blocking acquire would tie up a worker slot waiting on a build.
"""

import asyncio
import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import Connection
from sqlalchemy.engine import Engine

# Fallback for SQLite, which has no advisory locks. Correct only within one
# process — which is what the test suite is, and dev. Postgres is the real path.
_local_locks: dict[UUID, asyncio.Lock] = {}


def advisory_key(service_id: UUID) -> int:
    """Map a UUID onto the signed 64-bit integer advisory locks take."""
    digest = hashlib.sha1(service_id.bytes).digest()[:8]
    return int.from_bytes(digest, "big", signed=True)


@asynccontextmanager
async def service_deploy_lock(engine: Engine, service_id: UUID) -> AsyncIterator[bool]:
    """Yield True if this caller holds the deploy lock for the service.

    Yielding False rather than raising keeps the caller's control flow honest:
    "someone else is deploying this service" is an expected outcome, not an error.
    """
    if engine.dialect.name != "postgresql":
        async with _fallback_lock(service_id) as acquired:
            yield acquired
        return

    key = advisory_key(service_id)
    connection = await asyncio.to_thread(engine.connect)
    try:
        acquired = await asyncio.to_thread(_try_lock, connection, key)
        try:
            yield acquired
        finally:
            if acquired:
                await asyncio.to_thread(_unlock, connection, key)
    finally:
        await asyncio.to_thread(connection.close)


def _try_lock(connection: Connection, key: int) -> bool:
    result = connection.exec_driver_sql("SELECT pg_try_advisory_lock(%s)", (key,)).scalar()
    return bool(result)


def _unlock(connection: Connection, key: int) -> None:
    connection.exec_driver_sql("SELECT pg_advisory_unlock(%s)", (key,))
    connection.commit()


@asynccontextmanager
async def _fallback_lock(service_id: UUID) -> AsyncIterator[bool]:
    lock = _local_locks.setdefault(service_id, asyncio.Lock())
    if lock.locked():
        yield False
        return
    async with lock:
        yield True


def _reset_fallback_locks() -> None:
    """Test hook. Never call this from application code."""
    _local_locks.clear()
