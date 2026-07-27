"""Client for the agent to communicate with the control plane.
"""

from __future__ import annotations

import logging
import os

import aiohttp

from .config import AgentSettings
from .docker_ops import DockerOps

log = logging.getLogger(__name__)


class ControlPlaneClient:
    def __init__(self, settings: AgentSettings, ops: DockerOps):
        self._settings = settings
        self._ops = ops
        self._session: aiohttp.ClientSession | None = None

    def _client(self) -> aiohttp.ClientSession:
        """Create the client inside an active aiohttp event loop."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={"X-Rudder-Agent-Secret": self._settings.shared_secret}
            )
        return self._session

    async def register(self) -> None:
        """Register the node with the control plane."""
        log.info("Registering with control plane at %s", self._settings.control_plane_url)
        async with self._client().post(
            f"{self._settings.control_plane_url}/nodes/register",
            json={
                "hostname": self._settings.node_hostname,
                "ip_address": self._settings.advertise_address,
                **_capacity(),
            },
        ) as response:
            response.raise_for_status()
        log.info("Registration successful")

    async def heartbeat(self) -> None:
        """Send a heartbeat to the control plane with the current node state."""
        # TODO: Implement heartbeat logic
        log.info("Sending heartbeat to control plane")
        containers = await self._ops.list_containers()
        async with self._client().post(
            f"{self._settings.control_plane_url}/nodes/heartbeat",
            json={
                "hostname": self._settings.node_hostname,
                "containers": [c.model_dump(mode="json") for c in containers],
            },
        ) as response:
            response.raise_for_status()

    async def close(self) -> None:
        """Close the client session."""
        if self._session is not None:
            await self._session.close()


def _capacity() -> dict[str, float | int]:
    """Return the agent host's schedulable CPU and memory without extra deps."""
    cpu_total = float(os.cpu_count() or 1)
    try:
        memory_total_mb = int(
            os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / (1024 * 1024)
        )
    except (AttributeError, OSError, ValueError):
        memory_total_mb = 1024
    return {"cpu_total": cpu_total, "memory_total_mb": max(memory_total_mb, 1)}
