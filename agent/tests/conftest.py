"""Shared fixtures. The Docker client is injected through the constructor, so
none of these tests need a live Docker daemon."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from rudder_agent.config import AgentSettings
from rudder_agent.docker_ops import DockerOps
from rudder_agent.main import create_app

from .fakes import FakeDockerClient, SpecBuilder

# aiohttp's helpers are named Test*, which pytest would otherwise try to collect.
TestClient.__test__ = False  # type: ignore[attr-defined]
TestServer.__test__ = False  # type: ignore[attr-defined]


@pytest.fixture
def docker_client() -> FakeDockerClient:
    return FakeDockerClient()


@pytest.fixture
def settings() -> AgentSettings:
    # Drain to zero by default so lifecycle tests do not sleep. The drain window
    # itself is exercised explicitly in test_delete.py.
    return AgentSettings(drain_seconds=0.0)


@pytest.fixture
def ops(docker_client: FakeDockerClient) -> DockerOps:
    return DockerOps(docker_client, stop_timeout_seconds=1)


@pytest.fixture
async def client(ops: DockerOps, settings: AgentSettings) -> AsyncIterator[TestClient]:
    test_client = TestClient(TestServer(create_app(ops, settings)))
    await test_client.start_server()
    try:
        yield test_client
    finally:
        await test_client.close()


@pytest.fixture
def spec_body() -> SpecBuilder:
    def _build(**overrides: Any) -> dict[str, Any]:
        body: dict[str, Any] = {
            "image": "localhost:5000/svc:abc123",
            "name": "api-abc123",
            "env": {"DATABASE_URL": "postgres://u:p@db:5432/app"},
            "container_port": 8080,
            "cpu_limit": 0.5,
            "memory_limit_mb": 512,
            "network": "rudder",
            "labels": {"rudder.service": "api"},
        }
        body.update(overrides)
        return body

    return _build
