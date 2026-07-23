"""POST /containers."""

from __future__ import annotations

import docker.errors
from aiohttp.test_utils import TestClient

from .fakes import FakeDockerClient, SpecBuilder


async def test_create_returns_container_id(
    client: TestClient, docker_client: FakeDockerClient, spec_body: SpecBuilder
) -> None:
    resp = await client.post("/containers", json=spec_body())
    assert resp.status == 201
    body = await resp.json()
    assert body["id"] == docker_client.next_id
    assert body["name"] == "api-abc123"
    # Freshly created, not yet observed running: starting, never optimistic.
    assert body["status"] == "starting"
    assert body["docker_status"] == "created"


async def test_create_pulls_missing_image_then_starts(
    client: TestClient, docker_client: FakeDockerClient, spec_body: SpecBuilder
) -> None:
    resp = await client.post("/containers", json=spec_body())
    assert resp.status == 201
    assert docker_client.calls[:4] == [
        "images.get",
        "images.pull",
        "containers.create",
        "container.start",
    ]
    container = docker_client.containers.get(docker_client.next_id)
    assert container.started is True


async def test_create_does_not_pull_when_image_present(
    client: TestClient, docker_client: FakeDockerClient, spec_body: SpecBuilder
) -> None:
    docker_client.images.present.add("localhost:5000/svc:abc123")
    resp = await client.post("/containers", json=spec_body())
    assert resp.status == 201
    assert "images.pull" not in docker_client.calls


async def test_create_publishes_no_host_ports_and_applies_limits(
    client: TestClient, docker_client: FakeDockerClient, spec_body: SpecBuilder
) -> None:
    resp = await client.post("/containers", json=spec_body())
    assert resp.status == 201
    kwargs = docker_client.create_kwargs
    assert kwargs is not None
    # Deployed containers publish NO host ports — Traefik reaches them over the
    # shared docker network.
    assert kwargs["ports"] == {}
    assert kwargs["network"] == "rudder"
    assert kwargs["nano_cpus"] == 500_000_000
    assert kwargs["mem_limit"] == "512m"
    assert kwargs["environment"] == {"DATABASE_URL": "postgres://u:p@db:5432/app"}
    assert kwargs["labels"] == {"rudder.service": "api"}
    assert kwargs["detach"] is True


async def test_image_pull_failure_is_422_not_a_crash(
    client: TestClient, docker_client: FakeDockerClient, spec_body: SpecBuilder
) -> None:
    docker_client.pull_error = docker.errors.ImageNotFound("manifest unknown")
    resp = await client.post("/containers", json=spec_body())
    assert resp.status == 422
    body = await resp.json()
    assert body["code"] == "image_pull_failed"
    assert body["details"]["image"] == "localhost:5000/svc:abc123"
    assert set(body) == {"code", "message", "details"}


async def test_name_already_in_use_is_409(
    client: TestClient, spec_body: SpecBuilder
) -> None:
    first = await client.post("/containers", json=spec_body())
    assert first.status == 201
    second = await client.post("/containers", json=spec_body())
    assert second.status == 409
    body = await second.json()
    assert body["code"] == "container_name_in_use"
    assert body["details"]["name"] == "api-abc123"


async def test_failed_start_removes_the_container_and_returns_502(
    client: TestClient, docker_client: FakeDockerClient, spec_body: SpecBuilder
) -> None:
    docker_client.start_error = docker.errors.APIError("oci runtime error")
    resp = await client.post("/containers", json=spec_body())
    assert resp.status == 502
    body = await resp.json()
    assert body["code"] == "docker_error"
    # The name must not be left squatted on, or the control plane's retry 409s.
    assert "container.remove" in docker_client.calls


async def test_invalid_spec_is_400_with_details(client: TestClient) -> None:
    resp = await client.post("/containers", json={"image": "x"})
    assert resp.status == 400
    body = await resp.json()
    assert body["code"] == "invalid_request"
    missing = {tuple(e["loc"]) for e in body["details"]["errors"]}
    assert ("name",) in missing
    assert ("container_port",) in missing


async def test_non_json_body_is_400(client: TestClient) -> None:
    resp = await client.post(
        "/containers", data="not json", headers={"Content-Type": "application/json"}
    )
    assert resp.status == 400
    body = await resp.json()
    assert body["code"] == "invalid_request"


async def test_out_of_range_port_is_rejected(
    client: TestClient, spec_body: SpecBuilder
) -> None:
    resp = await client.post("/containers", json=spec_body(container_port=70000))
    assert resp.status == 400
    body = await resp.json()
    assert body["code"] == "invalid_request"
