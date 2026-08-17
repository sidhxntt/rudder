"""Bounded Docker runtime-log endpoint."""

from aiohttp.test_utils import TestClient

from .fakes import FakeContainer, FakeDockerClient


async def test_runtime_log_endpoint_returns_timestamped_tail(
    client: TestClient, docker_client: FakeDockerClient
) -> None:
    docker_client.containers.add(
        FakeContainer("abc", "api", logs=b"2026-08-17T00:00:00Z hello\\n")
    )

    response = await client.get("/containers/abc/runtime-logs?max_bytes=8")
    assert response.status == 200
    assert await response.json() == {"text": " hello\\n", "dropped_bytes": 20}


async def test_runtime_log_endpoint_bounds_query_size(client: TestClient) -> None:
    response = await client.get("/containers/abc/runtime-logs?max_bytes=0")
    assert response.status == 400
    assert (await response.json())["code"] == "invalid_request"
