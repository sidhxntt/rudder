"""HTTP client for the node agent.

D3(b): the control plane never touches Docker. It states desired state here and
the agent reports what actually happened. Phase 2 changes the base URL to a
scheduled node's address; nothing else about this file changes.
"""

from dataclasses import dataclass
from typing import Any

import httpx


class AgentError(Exception):
    """The agent refused or failed. The message reaches the user."""


@dataclass(frozen=True)
class ContainerState:
    id: str
    status: str
    docker_status: str | None = None
    exit_code: int | None = None
    ip_address: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "ContainerState":
        return cls(
            id=str(payload["id"]),
            status=str(payload["status"]),
            docker_status=payload.get("docker_status"),
            exit_code=payload.get("exit_code"),
            ip_address=payload.get("ip_address"),
        )


@dataclass(frozen=True)
class ProbeResult:
    ok: bool
    status_code: int | None
    reason: str | None


class AgentClient:
    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def create_container(
        self,
        *,
        image: str,
        name: str,
        env: dict[str, str],
        container_port: int,
        cpu_limit: float,
        memory_limit_mb: int,
        network: str,
        labels: dict[str, str] | None = None,
        network_aliases: list[str] | None = None,
        volumes: dict[str, dict[str, str]] | None = None,
        command: list[str] | None = None,
    ) -> ContainerState:
        payload = {
            "image": image,
            "name": name,
            "env": env,
            "container_port": container_port,
            "cpu_limit": cpu_limit,
            "memory_limit_mb": memory_limit_mb,
            "network": network,
            "labels": labels or {},
            "network_aliases": network_aliases or [],
            "volumes": volumes or {},
            "command": command,
        }
        return ContainerState.from_payload(await self._request("POST", "/containers", json=payload))

    async def inspect(self, container_id: str) -> ContainerState:
        return ContainerState.from_payload(
            await self._request("GET", f"/containers/{container_id}")
        )

    async def probe(
        self,
        container_id: str,
        *,
        path: str,
        port: int,
        protocol: str = "http",
        timeout_seconds: float = 5.0,
    ) -> ProbeResult:
        payload = await self._request(
            "POST",
            f"/containers/{container_id}/health",
            json={
                "path": path,
                "port": port,
                "protocol": protocol,
                "timeout_seconds": timeout_seconds,
            },
        )
        return ProbeResult(
            ok=bool(payload["ok"]),
            status_code=payload.get("status_code"),
            reason=payload.get("reason"),
        )

    async def remove(self, container_id: str, *, drain_seconds: float) -> None:
        # The agent treats deleting a missing container as success, so this is
        # safe to retry and safe to call on a container that already died.
        await self._request(
            "DELETE",
            f"/containers/{container_id}",
            params={"drain_seconds": drain_seconds},
            # Drain happens agent-side, so the client must outwait it.
            timeout=self._timeout + drain_seconds,
        )

    # ASYNC109: this is httpx's own request timeout, passed straight through,
    # not a cancellation scope the caller should be opening instead.
    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,  # noqa: ASYNC109
    ) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            async with httpx.AsyncClient(timeout=timeout or self._timeout) as client:
                response = await client.request(method, url, json=json, params=params)
        except httpx.HTTPError as exc:
            raise AgentError(f"Node agent unreachable at {self._base_url}: {exc}") from exc

        if response.status_code >= 400:
            raise AgentError(_describe(response))
        if not response.content:
            return {}
        return response.json()


def _describe(response: httpx.Response) -> str:
    """Turn the agent's uniform {code, message, details} into one user-facing line."""
    try:
        body = response.json()
    except ValueError:
        return f"Node agent returned {response.status_code}: {response.text[:200]}"
    message = body.get("message") or response.text[:200]
    code = body.get("code") or response.status_code
    return f"{code}: {message}"
