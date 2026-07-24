"""POST /containers/{id}/health — exactly ONE probe per call.

The D12 poll loop (60s timeout, 2s interval, 5s start grace, 1 success) lives in
the control plane. Nothing here loops.
"""

from __future__ import annotations

import socket
from collections.abc import AsyncIterator

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from .fakes import FakeContainer, FakeDockerClient, make_attrs


@pytest.fixture
async def app_server() -> AsyncIterator[TestServer]:
    """A stand-in for the deployed app, reachable at 127.0.0.1:<port>."""

    async def ok(request: web.Request) -> web.Response:
        return web.Response(text="alive")

    async def boom(request: web.Request) -> web.Response:
        return web.Response(status=503, text="not ready")

    app = web.Application()
    app.add_routes([web.get("/healthz", ok), web.get("/boom", boom)])
    server = TestServer(app, host="127.0.0.1")
    await server.start_server()
    try:
        yield server
    finally:
        await server.close()


def _closed_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


async def test_probe_success_returns_status_code(
    client: TestClient, docker_client: FakeDockerClient, app_server: TestServer
) -> None:
    docker_client.containers.add(FakeContainer("abc", "api-1", make_attrs(ip="127.0.0.1")))
    resp = await client.post(
        "/containers/abc/health", json={"path": "/healthz", "port": app_server.port}
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is True
    assert body["status_code"] == 200
    assert body["reason"] is None
    assert body["probed_url"] == f"http://127.0.0.1:{app_server.port}/healthz"
    assert body["latency_ms"] >= 0


async def test_tcp_probe_succeeds_without_an_http_response(
    client: TestClient, docker_client: FakeDockerClient, app_server: TestServer
) -> None:
    docker_client.containers.add(FakeContainer("abc", "redis-1", make_attrs(ip="127.0.0.1")))
    resp = await client.post(
        "/containers/abc/health", json={"protocol": "tcp", "port": app_server.port}
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is True
    assert body["status_code"] is None
    assert body["probed_url"] == f"tcp://127.0.0.1:{app_server.port}"


async def test_probe_non_2xx_is_a_result_not_an_error(
    client: TestClient, docker_client: FakeDockerClient, app_server: TestServer
) -> None:
    docker_client.containers.add(FakeContainer("abc", "api-1", make_attrs(ip="127.0.0.1")))
    resp = await client.post(
        "/containers/abc/health", json={"path": "/boom", "port": app_server.port}
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is False
    assert body["status_code"] == 503
    assert body["reason"] == "HTTP 503"


async def test_probe_connection_refused_reports_the_failure_reason(
    client: TestClient, docker_client: FakeDockerClient
) -> None:
    docker_client.containers.add(FakeContainer("abc", "api-1", make_attrs(ip="127.0.0.1")))
    resp = await client.post(
        "/containers/abc/health", json={"path": "/healthz", "port": _closed_port()}
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is False
    assert body["status_code"] is None
    assert "Cannot connect" in body["reason"] or "Connect" in body["reason"]


async def test_probe_container_without_ip_is_a_failed_result(
    client: TestClient, docker_client: FakeDockerClient
) -> None:
    docker_client.containers.add(
        FakeContainer("abc", "api-1", make_attrs(status="exited", ip=None))
    )
    resp = await client.post("/containers/abc/health", json={"port": 8080})
    assert resp.status == 200
    body = await resp.json()
    assert body["ok"] is False
    assert "no IP address" in body["reason"]


async def test_probe_named_network_that_is_not_attached(
    client: TestClient, docker_client: FakeDockerClient
) -> None:
    docker_client.containers.add(
        FakeContainer("abc", "api-1", make_attrs(ip="127.0.0.1", network="rudder"))
    )
    resp = await client.post(
        "/containers/abc/health", json={"port": 8080, "network": "somewhere-else"}
    )
    body = await resp.json()
    assert body["ok"] is False
    assert "somewhere-else" in body["reason"]


async def test_probe_unknown_container_is_404(client: TestClient) -> None:
    resp = await client.post("/containers/nope/health", json={"port": 8080})
    assert resp.status == 404
    assert (await resp.json())["code"] == "container_not_found"


async def test_probe_requires_a_port(client: TestClient, docker_client: FakeDockerClient) -> None:
    docker_client.containers.add(FakeContainer("abc", "api-1", make_attrs()))
    resp = await client.post("/containers/abc/health", json={"path": "/healthz"})
    assert resp.status == 400
    assert (await resp.json())["code"] == "invalid_request"
