"""Docker operations for one host.

Every call into the Docker SDK is blocking socket I/O, and this is an asyncio
server — so each one is dispatched to a thread executor via `asyncio.to_thread`.
Nothing in this module touches the event loop while waiting on Docker.

The agent owns ACTUAL state only. It is told about one container at a time and
reports what it observes.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any, TypeVar

import aiohttp
import docker.errors
from docker import DockerClient
from docker.models.containers import Container
from docker.types import EndpointConfig

from . import errors
from .schemas import (
    ContainerSpec,
    ContainerState,
    DeleteResult,
    HealthProbeRequest,
    HealthProbeResult,
    InstanceStatus,
)

T = TypeVar("T")

_NANO_CPUS_PER_CORE = 1_000_000_000


def map_status(docker_status: str, health: str | None) -> InstanceStatus:
    """Map Docker's container state onto the Instance status vocabulary.

    Deliberately pessimistic. A running container with no Docker HEALTHCHECK is
    reported `starting`, not `healthy`: nothing has confirmed the app serves
    traffic yet. The control plane promotes it to healthy from the result of
    POST /containers/{id}/health, which is where that judgement belongs.
    """
    if docker_status == "running":
        if health == "healthy":
            return InstanceStatus.HEALTHY
        if health == "unhealthy":
            return InstanceStatus.UNHEALTHY
        # health in {None, "starting", "none"}
        return InstanceStatus.STARTING
    if docker_status == "created":
        return InstanceStatus.STARTING
    if docker_status == "restarting":
        # Crash-looping. Not "starting" — it already failed at least once.
        return InstanceStatus.UNHEALTHY
    if docker_status == "paused":
        # Up but serving nothing.
        return InstanceStatus.UNHEALTHY
    if docker_status in ("exited", "dead", "removing"):
        return InstanceStatus.STOPPED
    # Unknown Docker state: do not guess in the optimistic direction.
    return InstanceStatus.UNHEALTHY


def _network_ip(attrs: dict[str, Any], network: str | None) -> str | None:
    networks = attrs.get("NetworkSettings", {}).get("Networks") or {}
    if network is not None:
        return networks.get(network, {}).get("IPAddress") or None
    for entry in networks.values():
        ip = entry.get("IPAddress")
        if ip:
            return str(ip)
    return None


def state_from_container(container: Container, draining: bool = False) -> ContainerState:
    attrs: dict[str, Any] = container.attrs or {}
    state: dict[str, Any] = attrs.get("State", {}) or {}
    docker_status = str(state.get("Status") or container.status or "unknown")
    health_block = state.get("Health") or {}
    health = health_block.get("Status")
    mapped = InstanceStatus.DRAINING if draining else map_status(docker_status, health)
    return ContainerState(
        id=container.id,
        name=container.name,
        status=mapped,
        docker_status=docker_status,
        docker_health=health,
        exit_code=state.get("ExitCode"),
        started_at=state.get("StartedAt"),
        ip_address=_network_ip(attrs, None),
        image=(attrs.get("Config", {}) or {}).get("Image"),
    )


class DockerOps:
    """Thin, concrete wrapper over the Docker SDK. No runtime abstraction —
    this is Docker, and only Docker (PRD "Working Agreement", rule 3)."""

    def __init__(self, client: DockerClient, stop_timeout_seconds: int = 10) -> None:
        self._client = client
        self._stop_timeout = stop_timeout_seconds
        # Container ids currently inside their drain window. Lets GET report
        # `draining` truthfully while DELETE is in flight.
        self._draining: set[str] = set()

    # ---------------------------------------------------------------- helpers

    @staticmethod
    async def _off_loop(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        """Run one blocking Docker SDK call in the default thread executor."""
        return await asyncio.to_thread(func, *args, **kwargs)

    async def _get(self, container_id: str) -> Container:
        try:
            return await self._off_loop(self._client.containers.get, container_id)
        except docker.errors.NotFound as exc:
            raise errors.container_not_found(container_id) from exc
        except docker.errors.APIError as exc:
            raise _translate_api_error(exc) from exc
        except docker.errors.DockerException as exc:
            raise errors.docker_unavailable(str(exc)) from exc

    # ------------------------------------------------------------------ create

    async def create_and_start(self, spec: ContainerSpec) -> ContainerState:
        await self._ensure_image(spec.image)

        kwargs: dict[str, Any] = {
            "image": spec.image,
            "name": spec.name,
            "environment": dict(spec.env),
            "labels": dict(spec.labels),
            # docker-py's high-level `containers.create` does not accept the
            # `network_aliases` shorthand. It requires the `network` selector
            # plus its raw endpoint mapping; ContainerCollection.create wraps
            # that mapping in NetworkingConfig itself.
            "network": spec.network,
            "networking_config": {
                spec.network: EndpointConfig(
                    getattr(getattr(self._client, "api", None), "_version", "1.41"),
                    aliases=list(spec.network_aliases),
                )
            },
            "volumes": dict(spec.volumes),
            "command": spec.command,
            "detach": True,
            "nano_cpus": int(spec.cpu_limit * _NANO_CPUS_PER_CORE),
            "mem_limit": f"{spec.memory_limit_mb}m",
            # Deployed containers publish NO host ports. Traefik reaches them
            # over the shared Docker network — that is what lets two versions of
            # a service run at once during a rolling deploy.
            "ports": {},
        }

        try:
            container: Container = await self._off_loop(self._client.containers.create, **kwargs)
        except docker.errors.ImageNotFound as exc:
            raise errors.image_pull_failed(spec.image, str(exc)) from exc
        except docker.errors.APIError as exc:
            if _status_code(exc) == 409:
                raise errors.name_conflict(spec.name) from exc
            raise _translate_api_error(exc) from exc
        except docker.errors.DockerException as exc:
            raise errors.docker_unavailable(str(exc)) from exc

        try:
            await self._off_loop(container.start)
        except docker.errors.APIError as exc:
            await self._best_effort_remove(container)
            raise _translate_api_error(exc) from exc
        except docker.errors.DockerException as exc:
            await self._best_effort_remove(container)
            raise errors.docker_unavailable(str(exc)) from exc

        return await self.inspect(container.id)

    async def _ensure_image(self, image: str) -> None:
        """Pull the image if the daemon does not already have it."""
        try:
            await self._off_loop(self._client.images.get, image)
            return
        except docker.errors.ImageNotFound:
            pass
        except docker.errors.APIError as exc:
            raise _translate_api_error(exc) from exc
        except docker.errors.DockerException as exc:
            raise errors.docker_unavailable(str(exc)) from exc

        try:
            await self._off_loop(self._client.images.pull, image)
        except docker.errors.APIError as exc:
            # Covers ImageNotFound/NotFound (bad tag) and the registry errors
            # that surface as a plain APIError — e.g. the missing
            # `insecure-registries` entry, which reads as a TLS failure.
            raise errors.image_pull_failed(image, str(exc)) from exc
        except docker.errors.DockerException as exc:
            raise errors.docker_unavailable(str(exc)) from exc

    async def _best_effort_remove(self, container: Container) -> None:
        """A container that failed to start must not squat on its name."""
        try:
            await self._off_loop(container.remove, force=True)
        except docker.errors.DockerException:
            return

    # ----------------------------------------------------------------- inspect

    async def inspect(self, container_id: str) -> ContainerState:
        container = await self._get(container_id)
        return state_from_container(container, draining=container.id in self._draining)

    # ------------------------------------------------------------------ delete

    async def drain_and_remove(self, container_id: str, drain_seconds: float) -> DeleteResult:
        """D10: after traffic has shifted, the old container drains for a window
        and is then stopped and removed.

        Draining in Phase 1 is a sleep, not connection tracking. Deleting an
        already-deleted container succeeds — the control plane retries.
        """
        try:
            container = await self._get(container_id)
        except errors.AgentError as exc:
            if exc.code == "container_not_found":
                return DeleteResult(
                    id=container_id,
                    status=InstanceStatus.STOPPED,
                    removed=False,
                    drained_seconds=0.0,
                )
            raise

        self._draining.add(container.id)
        try:
            if drain_seconds > 0:
                await asyncio.sleep(drain_seconds)

            try:
                await self._off_loop(container.stop, timeout=self._stop_timeout)
            except docker.errors.NotFound:
                return DeleteResult(
                    id=container_id,
                    status=InstanceStatus.STOPPED,
                    removed=False,
                    drained_seconds=drain_seconds,
                )
            except docker.errors.APIError as exc:
                raise _translate_api_error(exc) from exc

            try:
                await self._off_loop(container.remove, v=False, force=True)
            except docker.errors.NotFound:
                pass
            except docker.errors.APIError as exc:
                raise _translate_api_error(exc) from exc
        finally:
            self._draining.discard(container.id)

        return DeleteResult(
            id=container.id,
            status=InstanceStatus.STOPPED,
            removed=True,
            drained_seconds=drain_seconds,
        )

    # ------------------------------------------------------------------- probe

    async def probe(self, container_id: str, req: HealthProbeRequest) -> HealthProbeResult:
        """Run exactly ONE health probe against the container, over the Docker
        network. No loop, no retries — those are the control plane's (D12)."""
        container = await self._get(container_id)
        ip = _network_ip(container.attrs or {}, req.network)
        if not ip:
            where = f"network {req.network!r}" if req.network else "any attached network"
            return HealthProbeResult(
                ok=False,
                reason=f"container has no IP address on {where}",
                latency_ms=0.0,
            )

        if req.protocol == "tcp":
            return await _tcp_probe(ip, req.port, req.timeout_seconds)
        path = req.path if req.path.startswith("/") else f"/{req.path}"
        url = f"http://{ip}:{req.port}{path}"
        timeout = aiohttp.ClientTimeout(total=req.timeout_seconds)
        started = time.monotonic()
        try:
            async with (
                aiohttp.ClientSession(timeout=timeout) as session,
                session.get(url, allow_redirects=False) as resp,
            ):
                await resp.read()
                elapsed = (time.monotonic() - started) * 1000
                return HealthProbeResult(
                        ok=200 <= resp.status < 300,
                        status_code=resp.status,
                        reason=None if 200 <= resp.status < 300 else f"HTTP {resp.status}",
                        latency_ms=round(elapsed, 3),
                        probed_url=url,
                    )
        except TimeoutError:
            elapsed = (time.monotonic() - started) * 1000
            return HealthProbeResult(
                ok=False,
                reason=f"timed out after {req.timeout_seconds}s",
                latency_ms=round(elapsed, 3),
                probed_url=url,
            )
        except aiohttp.ClientError as exc:
            elapsed = (time.monotonic() - started) * 1000
            return HealthProbeResult(
                ok=False,
                reason=f"{type(exc).__name__}: {exc}",
                latency_ms=round(elapsed, 3),
                probed_url=url,
            )


async def _tcp_probe(ip: str, port: int, timeout_seconds: float) -> HealthProbeResult:
    started = time.monotonic()
    url = f"tcp://{ip}:{port}"
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port), timeout_seconds
        )
        del reader
        writer.close()
        await writer.wait_closed()
        return HealthProbeResult(
            ok=True,
            latency_ms=round((time.monotonic() - started) * 1000, 3),
            probed_url=url,
        )
    except (OSError, TimeoutError) as exc:
        return HealthProbeResult(
            ok=False,
            reason=f"{type(exc).__name__}: {exc}",
            latency_ms=round((time.monotonic() - started) * 1000, 3),
            probed_url=url,
        )


def _status_code(exc: docker.errors.APIError) -> int | None:
    code = getattr(exc, "status_code", None)
    return int(code) if isinstance(code, int) else None


def _translate_api_error(exc: docker.errors.APIError) -> errors.AgentError:
    """Any Docker API rejection we have not special-cased is an upstream
    failure, not a client error: 502 with the daemon's own status attached."""
    return errors.docker_error(str(exc), {"docker_status": _status_code(exc)})
