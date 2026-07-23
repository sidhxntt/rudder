"""Build log store + SSE stream.

The invariant under test is the one Phase 1 calls out: logs go to a file, SSE
tails the file, and a client hanging up never touches the build.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rudder_cp.logs.sse import frame
from rudder_cp.logs.store import (
    BuildLogNotFound,
    BuildLogStore,
    InvalidDeploymentId,
    LogEvent,
    get_build_log_store,
    terminal_marker,
)
from rudder_cp.routers import logs as logs_router

TIMEOUT = 5.0


@pytest.fixture
def store(tmp_path: Path) -> BuildLogStore:
    return BuildLogStore(tmp_path)


@pytest.fixture
def deployment_id() -> UUID:
    return uuid4()


async def drain(events: AsyncIterator[LogEvent]) -> tuple[str, str]:
    """Consume a tail to completion. Returns (log text, terminal status)."""

    async def _run() -> tuple[str, str]:
        text = ""
        status = ""
        async for event in events:
            if event.kind == "chunk":
                text += event.text
            elif event.kind == "end":
                status = event.text
        return text, status

    return await asyncio.wait_for(_run(), TIMEOUT)


def make_app(store: BuildLogStore) -> FastAPI:
    app = FastAPI()
    app.include_router(logs_router.router)
    app.dependency_overrides[get_build_log_store] = lambda: store
    return app


# -- path derivation ---------------------------------------------------------


def test_path_is_derived_from_the_uuid(store: BuildLogStore, deployment_id: UUID) -> None:
    path = store.path_for(deployment_id)
    assert path.parent == store.root.resolve()
    assert path.name == f"{deployment_id}.log"
    assert store.path_for(str(deployment_id)) == path


@pytest.mark.parametrize(
    "bad",
    ["../../etc/passwd", "..", "/etc/passwd", "a/../../b", "", "not-a-uuid"],
)
def test_path_rejects_traversal(store: BuildLogStore, bad: str) -> None:
    with pytest.raises(InvalidDeploymentId):
        store.path_for(bad)


def test_traversal_never_creates_a_file_outside_the_log_dir(
    store: BuildLogStore, tmp_path: Path
) -> None:
    with pytest.raises(InvalidDeploymentId):
        store.exists("../../etc/passwd")
    assert list(tmp_path.iterdir()) == []


# -- write then read ---------------------------------------------------------


async def test_append_then_read_returns_content(store: BuildLogStore, deployment_id: UUID) -> None:
    await store.open_log(deployment_id)
    await store.append(deployment_id, "#1 resolve image\n")
    await store.append(deployment_id, "#2 done\n")
    await store.close_log(deployment_id, "succeeded")

    text, status = await drain(store.tail(deployment_id, poll_interval=0.01))
    assert text == "#1 resolve image\n#2 done\n"
    assert status == "succeeded"


async def test_reader_attached_after_completion_gets_everything_and_terminates(
    store: BuildLogStore, deployment_id: UUID
) -> None:
    await store.open_log(deployment_id)
    for i in range(50):
        await store.append(deployment_id, f"line {i}\n")
    await store.close_log(deployment_id, "failed")

    # Attaching well after the build ended must not hang.
    text, status = await drain(store.tail(deployment_id, poll_interval=0.01))
    assert text.splitlines() == [f"line {i}" for i in range(50)]
    assert status == "failed"


async def test_reader_attached_mid_write_receives_later_appends(
    store: BuildLogStore, deployment_id: UUID
) -> None:
    await store.open_log(deployment_id)
    await store.append(deployment_id, "step 1\n")

    events = store.tail(deployment_id, poll_interval=0.01)
    first = await asyncio.wait_for(anext(events), TIMEOUT)
    assert first == LogEvent("chunk", "step 1\n")

    await store.append(deployment_id, "step 2\n")
    second = await asyncio.wait_for(anext(events), TIMEOUT)
    assert second == LogEvent("chunk", "step 2\n")

    await store.close_log(deployment_id, "succeeded")
    third = await asyncio.wait_for(anext(events), TIMEOUT)
    assert third == LogEvent("end", "succeeded")

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(anext(events), TIMEOUT)


async def test_unknown_deployment_raises_rather_than_hanging(store: BuildLogStore) -> None:
    with pytest.raises(BuildLogNotFound):
        await asyncio.wait_for(anext(store.tail(uuid4())), TIMEOUT)


async def test_keepalive_is_emitted_while_the_build_is_idle(
    store: BuildLogStore, deployment_id: UUID
) -> None:
    await store.open_log(deployment_id)
    events = store.tail(deployment_id, poll_interval=0.01, keepalive_interval=0.02)
    event = await asyncio.wait_for(anext(events), TIMEOUT)
    assert event.kind == "keepalive"
    await events.aclose()


async def test_terminal_marker_never_leaks_into_the_stream(
    store: BuildLogStore, deployment_id: UUID
) -> None:
    """Build output containing the sentinel must not fake a terminal marker."""
    await store.open_log(deployment_id)
    await store.append(deployment_id, terminal_marker("succeeded"))
    await store.append(deployment_id, "still building\n")
    await store.close_log(deployment_id, "failed")

    text, status = await drain(store.tail(deployment_id, poll_interval=0.01))
    assert "\x04" not in text
    assert "still building\n" in text
    assert status == "failed"


# -- disconnect --------------------------------------------------------------


async def test_disconnecting_reader_does_not_affect_the_writer(
    store: BuildLogStore, deployment_id: UUID
) -> None:
    await store.open_log(deployment_id)
    await store.append(deployment_id, "step 1\n")

    events = store.tail(deployment_id, poll_interval=0.01)
    assert (await asyncio.wait_for(anext(events), TIMEOUT)).text == "step 1\n"
    await events.aclose()  # client hung up

    # The build carries on regardless.
    await store.append(deployment_id, "step 2\n")
    await store.close_log(deployment_id, "succeeded")

    text, status = await drain(store.tail(deployment_id, poll_interval=0.01))
    assert text == "step 1\nstep 2\n"
    assert status == "succeeded"


async def test_closing_a_tail_releases_the_file_handle(
    store: BuildLogStore, deployment_id: UUID
) -> None:
    await store.open_log(deployment_id)
    await store.append(deployment_id, "hello\n")
    await store.close_log(deployment_id, "succeeded")

    for _ in range(200):
        events = store.tail(deployment_id, poll_interval=0.01)
        await asyncio.wait_for(anext(events), TIMEOUT)
        await events.aclose()


# -- SSE framing -------------------------------------------------------------


def test_sse_framing() -> None:
    assert frame(LogEvent("chunk", "a\nb\n")) == "data: a\ndata: b\ndata: \n\n"
    assert frame(LogEvent("keepalive", "")) == ": keepalive\n\n"
    assert frame(LogEvent("end", "succeeded")) == "event: end\ndata: succeeded\n\n"


# -- HTTP --------------------------------------------------------------------


def test_endpoint_streams_a_finished_build(store: BuildLogStore, deployment_id: UUID) -> None:
    async def write() -> None:
        await store.open_log(deployment_id)
        await store.append(deployment_id, "#1 building\n")
        await store.close_log(deployment_id, "succeeded")

    asyncio.run(write())

    with TestClient(make_app(store)) as client:
        response = client.get(f"/deployments/{deployment_id}/build-log")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "data: #1 building" in response.text
    assert response.text.endswith("event: end\ndata: succeeded\n\n")


def test_endpoint_404s_for_a_deployment_with_no_log(store: BuildLogStore) -> None:
    with TestClient(make_app(store)) as client:
        response = client.get(f"/deployments/{uuid4()}/build-log")
    assert response.status_code == 404


def test_endpoint_rejects_a_non_uuid_path_segment(store: BuildLogStore) -> None:
    """A traversal attempt cannot even reach the store: the path param is a UUID."""
    with TestClient(make_app(store)) as client:
        response = client.get("/deployments/not-a-uuid/build-log")
        assert response.status_code == 422
        traversal = client.get("/deployments/..%2F..%2Fetc%2Fpasswd/build-log")
        assert traversal.status_code in (404, 422)
    assert not list(store.root.iterdir())
