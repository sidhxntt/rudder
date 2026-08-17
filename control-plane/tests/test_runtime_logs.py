"""Bounded runtime-log persistence and SSE tail behaviour."""

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from rudder_cp.logs.runtime import ACTIVE_BYTES, RuntimeLogStore


async def test_snapshots_deduplicate_and_tail_new_data(tmp_path: Path) -> None:
    store = RuntimeLogStore(tmp_path)
    service_id = uuid4()
    assert await store.append_snapshot(service_id, "one\\ntwo\\n") == len("one\\ntwo\\n")
    assert await store.append_snapshot(service_id, "two\\nthree\\n") == len("three\\n")

    events = store.tail(service_id, poll_interval=0.01)
    first = await asyncio.wait_for(anext(events), 1)
    assert first.text == "one\\ntwo\\nthree\\n"
    await store.append_snapshot(service_id, "three\\nfour\\n")
    second = await asyncio.wait_for(anext(events), 1)
    assert second.text == "four\\n"
    await events.aclose()


async def test_log_flood_rotates_at_fixed_cap(tmp_path: Path) -> None:
    store = RuntimeLogStore(tmp_path)
    service_id = uuid4()
    await store.append_snapshot(service_id, "a" * ACTIVE_BYTES)
    await store.append_snapshot(service_id, "a" * ACTIVE_BYTES + "b")

    active = store.path_for(service_id)
    archive = active.with_suffix(".log.1")
    assert 0 < active.stat().st_size <= ACTIVE_BYTES
    assert archive.stat().st_size == ACTIVE_BYTES


async def test_agent_drop_is_visible_in_persisted_log(tmp_path: Path) -> None:
    store = RuntimeLogStore(tmp_path)
    service_id = uuid4()
    await store.append_snapshot(service_id, "hello\\n", dropped_bytes=42)
    assert "dropped 42 log bytes" in store.path_for(service_id).read_text()


def test_runtime_log_paths_reject_non_uuid(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        RuntimeLogStore(tmp_path).path_for("../../etc/passwd")
