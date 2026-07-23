"""Every Docker SDK call is blocking socket I/O and this is an asyncio server.

These tests are the guard rail: the calls must leave the event loop thread, and
a slow daemon must not stall the whole agent.
"""

from __future__ import annotations

import asyncio
import threading

from aiohttp.test_utils import TestClient

from .fakes import FakeContainer, FakeDockerClient, SpecBuilder, make_attrs


async def test_docker_calls_run_off_the_event_loop_thread(
    client: TestClient, docker_client: FakeDockerClient
) -> None:
    docker_client.containers.add(FakeContainer("abc", "api-1", make_attrs()))
    loop_thread = threading.get_ident()

    resp = await client.get("/containers/abc")
    assert resp.status == 200

    assert docker_client.call_threads, "no docker call was recorded"
    assert all(tid != loop_thread for tid in docker_client.call_threads)


async def test_blocking_docker_call_does_not_block_the_loop(
    client: TestClient, docker_client: FakeDockerClient, spec_body: SpecBuilder
) -> None:
    gate = threading.Event()
    docker_client.gate = gate

    create = asyncio.create_task(client.post("/containers", json=spec_body()))
    await asyncio.sleep(0.05)  # let the request reach the blocked docker call
    assert not create.done()

    # The loop is still serving while the docker thread is parked on the gate.
    healthz = await asyncio.wait_for(client.get("/healthz"), timeout=1.0)
    assert healthz.status == 200
    assert await healthz.json() == {"status": "ok"}

    gate.set()
    resp = await asyncio.wait_for(create, timeout=5.0)
    assert resp.status == 201


async def test_drain_sleep_does_not_block_the_loop(
    client: TestClient, docker_client: FakeDockerClient
) -> None:
    docker_client.containers.add(FakeContainer("abc", "api-1", make_attrs(), docker_client))
    delete = asyncio.create_task(client.delete("/containers/abc?drain_seconds=0.5"))
    await asyncio.sleep(0.05)

    healthz = await asyncio.wait_for(client.get("/healthz"), timeout=0.2)
    assert healthz.status == 200

    assert (await asyncio.wait_for(delete, timeout=5.0)).status == 200
