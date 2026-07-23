"""GET /containers/{id} — Docker state mapped onto the Instance vocabulary."""

from __future__ import annotations

import docker.errors
import pytest
from aiohttp.test_utils import TestClient

from rudder_agent.docker_ops import map_status
from rudder_agent.schemas import InstanceStatus

from .fakes import FakeContainer, FakeDockerClient, make_attrs


@pytest.mark.parametrize(
    ("docker_status", "health", "expected"),
    [
        ("created", None, "starting"),
        ("running", None, "starting"),
        ("running", "starting", "starting"),
        ("running", "healthy", "healthy"),
        ("running", "unhealthy", "unhealthy"),
        ("restarting", None, "unhealthy"),
        ("paused", None, "unhealthy"),
        ("exited", None, "stopped"),
        ("dead", None, "stopped"),
        ("removing", None, "stopped"),
        ("something-new", None, "unhealthy"),
    ],
)
def test_status_mapping_table(docker_status: str, health: str | None, expected: str) -> None:
    assert map_status(docker_status, health) == InstanceStatus(expected)


@pytest.mark.parametrize(
    ("docker_status", "health", "expected"),
    [
        ("created", None, "starting"),
        ("running", None, "starting"),
        ("running", "healthy", "healthy"),
        ("running", "unhealthy", "unhealthy"),
        ("restarting", None, "unhealthy"),
        ("paused", None, "unhealthy"),
        ("exited", None, "stopped"),
        ("dead", None, "stopped"),
    ],
)
async def test_inspect_maps_each_docker_state(
    client: TestClient,
    docker_client: FakeDockerClient,
    docker_status: str,
    health: str | None,
    expected: str,
) -> None:
    docker_client.containers.add(
        FakeContainer("abc", "api-1", make_attrs(status=docker_status, health=health))
    )
    resp = await client.get("/containers/abc")
    assert resp.status == 200
    body = await resp.json()
    assert body["status"] == expected
    assert body["docker_status"] == docker_status
    assert body["docker_health"] == health


async def test_inspect_reports_observed_fields(
    client: TestClient, docker_client: FakeDockerClient
) -> None:
    docker_client.containers.add(
        FakeContainer("abc", "api-1", make_attrs(status="exited", exit_code=137))
    )
    body = await (await client.get("/containers/abc")).json()
    assert body["exit_code"] == 137
    assert body["ip_address"] == "172.20.0.5"
    assert body["image"] == "localhost:5000/svc:abc123"
    assert body["started_at"] == "2026-07-23T10:00:00.000000000Z"


async def test_inspect_unknown_container_is_404(client: TestClient) -> None:
    resp = await client.get("/containers/nope")
    assert resp.status == 404
    body = await resp.json()
    assert body == {
        "code": "container_not_found",
        "message": "No container with id 'nope' on this host",
        "details": {"container_id": "nope"},
    }


async def test_docker_daemon_down_is_503(
    client: TestClient, docker_client: FakeDockerClient
) -> None:
    docker_client.get_error = docker.errors.DockerException("connection refused")
    resp = await client.get("/containers/abc")
    assert resp.status == 503
    body = await resp.json()
    assert body["code"] == "docker_unavailable"
    assert set(body) == {"code", "message", "details"}


async def test_docker_api_error_is_502_with_daemon_status(
    client: TestClient, docker_client: FakeDockerClient
) -> None:
    class _Resp:
        status_code = 500
        reason = "Server Error"
        url = "http+docker://localhost/v1.45/containers/abc/json"

    docker_client.get_error = docker.errors.APIError("boom", response=_Resp())
    resp = await client.get("/containers/abc")
    assert resp.status == 502
    body = await resp.json()
    assert body["code"] == "docker_error"
    assert body["details"]["docker_status"] == 500
