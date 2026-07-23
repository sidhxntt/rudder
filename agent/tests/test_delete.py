"""DELETE /containers/{id} — D10 drain then stop. Draining is a sleep in
Phase 1, not connection tracking."""

from __future__ import annotations

import asyncio
import time

from aiohttp.test_utils import TestClient

from .fakes import FakeContainer, FakeDockerClient, make_attrs


async def test_delete_of_missing_container_is_idempotent_success(client: TestClient) -> None:
    resp = await client.delete("/containers/gone")
    assert resp.status == 200
    body = await resp.json()
    assert body == {
        "id": "gone",
        "status": "stopped",
        "removed": False,
        "drained_seconds": 0.0,
    }


async def test_delete_twice_succeeds(
    client: TestClient, docker_client: FakeDockerClient
) -> None:
    docker_client.containers.add(FakeContainer("abc", "api-1", make_attrs(), docker_client))
    first = await client.delete("/containers/abc")
    assert first.status == 200
    assert (await first.json())["removed"] is True

    second = await client.delete("/containers/abc")
    assert second.status == 200
    assert (await second.json())["removed"] is False


async def test_delete_stops_then_removes(
    client: TestClient, docker_client: FakeDockerClient
) -> None:
    container = docker_client.containers.add(
        FakeContainer("abc", "api-1", make_attrs(), docker_client)
    )
    resp = await client.delete("/containers/abc")
    assert resp.status == 200
    assert container.stopped is True
    assert container.removed is True
    assert docker_client.calls[-2:] == ["container.stop", "container.remove"]


async def test_drain_window_is_honoured_and_reported(
    client: TestClient, docker_client: FakeDockerClient
) -> None:
    docker_client.containers.add(FakeContainer("abc", "api-1", make_attrs(), docker_client))
    started = time.monotonic()
    resp = await client.delete("/containers/abc?drain_seconds=0.25")
    elapsed = time.monotonic() - started
    assert resp.status == 200
    assert (await resp.json())["drained_seconds"] == 0.25
    assert elapsed >= 0.25


async def test_container_reports_draining_during_the_window(
    client: TestClient, docker_client: FakeDockerClient
) -> None:
    docker_client.containers.add(FakeContainer("abc", "api-1", make_attrs(), docker_client))
    delete_task = asyncio.create_task(client.delete("/containers/abc?drain_seconds=0.4"))
    await asyncio.sleep(0.1)

    body = await (await client.get("/containers/abc")).json()
    assert body["status"] == "draining"
    # Raw Docker truth is still reported alongside the mapped status.
    assert body["docker_status"] == "running"

    resp = await delete_task
    assert resp.status == 200


async def test_negative_drain_seconds_is_400(client: TestClient) -> None:
    resp = await client.delete("/containers/abc?drain_seconds=-1")
    assert resp.status == 400
    assert (await resp.json())["code"] == "invalid_request"


async def test_non_numeric_drain_seconds_is_400(client: TestClient) -> None:
    resp = await client.delete("/containers/abc?drain_seconds=soon")
    assert resp.status == 400
    assert (await resp.json())["code"] == "invalid_request"
