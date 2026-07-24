"""Resolve safe Docker Compose manifests for imported repositories.

Compose is intentionally a constrained input format here.  Rudder owns the
Docker host, networks, project namespace, and public routing; an imported
repository may describe application services, but it may not escape into host
resources or configure its own networking topology.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import yaml

COMPOSE_FILENAMES = (
    "compose.yaml",
    "compose.yml",
    "docker-compose.yaml",
    "docker-compose.yml",
)
_SERVICE_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,62}$")
_MAX_MANIFEST_BYTES = 64 * 1024


class ComposeValidationError(ValueError):
    """The repository Compose file asks for an unsafe host capability."""


@dataclass(frozen=True, slots=True)
class ComposeService:
    name: str
    public_port: int | None


@dataclass(frozen=True, slots=True)
class ComposePlan:
    source: Literal["repository", "generated"]
    yaml: str
    services: dict[str, ComposeService]


class RepositoryFileReader(Protocol):
    async def file_at_ref(
        self, installation_id: int, repo: str, branch: str, path: str
    ) -> str | None: ...


async def resolve_compose_plan(
    reader: RepositoryFileReader,
    *,
    installation_id: int,
    repository: str,
    branch: str,
    selected_addons: set[str],
) -> ComposePlan:
    """Prefer the first supported repository Compose file over Rudder's plan."""
    for filename in COMPOSE_FILENAMES:
        manifest = await reader.file_at_ref(installation_id, repository, branch, filename)
        if manifest is not None:
            return parse_repository_compose(manifest)
    return generated_compose_plan(selected_addons)


def parse_repository_compose(manifest: str) -> ComposePlan:
    """Validate and normalize a repository-owned Compose document.

    Published ports are converted to internal ``expose`` declarations.  The
    public port is only metadata for Rudder's Traefik route: Compose itself
    never binds an imported service directly to the Docker host.
    """
    if len(manifest.encode()) > _MAX_MANIFEST_BYTES:
        raise ComposeValidationError("Compose manifest exceeds 64 KiB.")
    try:
        document = yaml.safe_load(manifest)
    except yaml.YAMLError as exc:
        raise ComposeValidationError("Compose manifest is not valid YAML.") from exc
    if not isinstance(document, dict):
        raise ComposeValidationError("Compose manifest must be a mapping.")
    services = document.get("services")
    if not isinstance(services, dict) or not services:
        raise ComposeValidationError("Compose manifest must declare at least one service.")
    if "networks" in document:
        raise ComposeValidationError("Custom Compose networks are not supported.")

    normalized_services: dict[str, dict[str, Any]] = {}
    plan_services: dict[str, ComposeService] = {}
    for name, raw_service in services.items():
        if not isinstance(name, str) or not _SERVICE_NAME.fullmatch(name):
            raise ComposeValidationError("Compose service names must be lowercase Docker names.")
        if not isinstance(raw_service, dict):
            raise ComposeValidationError(f"Compose service {name} must be a mapping.")
        service = dict(raw_service)
        _validate_service(name, service)
        public_port = _public_port(name, service.pop("ports", None))
        if public_port is not None:
            expose = service.get("expose", [])
            if isinstance(expose, (str, int)):
                expose = [expose]
            if not isinstance(expose, list):
                raise ComposeValidationError(f"Compose service {name} has an invalid expose value.")
            public_port_text = str(public_port)
            if public_port_text not in {str(value) for value in expose}:
                expose.append(public_port_text)
            service["expose"] = expose
        normalized_services[name] = service
        plan_services[name] = ComposeService(name=name, public_port=public_port)

    normalized = {
        key: value for key, value in document.items() if key not in {"version", "services"}
    }
    normalized["services"] = normalized_services
    return ComposePlan(
        source="repository",
        yaml=yaml.safe_dump(normalized, sort_keys=False),
        services=plan_services,
    )


def generated_compose_plan(selected_addons: set[str]) -> ComposePlan:
    """Return Rudder's minimal Compose plan for a detected Node application."""
    services: dict[str, dict[str, Any]] = {
        "app": {"build": ".", "expose": ["3000"]},
    }
    plan_services = {"app": ComposeService(name="app", public_port=3000)}
    volumes: dict[str, dict[str, object]] = {}
    if "postgres" in selected_addons:
        services["postgres"] = {
            "image": "postgres:16-alpine",
            "volumes": ["postgres-data:/var/lib/postgresql/data"],
        }
        volumes["postgres-data"] = {}
        plan_services["postgres"] = ComposeService(name="postgres", public_port=None)
    if "redis" in selected_addons:
        services["redis"] = {"image": "redis:7-alpine", "volumes": ["redis-data:/data"]}
        volumes["redis-data"] = {}
        plan_services["redis"] = ComposeService(name="redis", public_port=None)
    document: dict[str, Any] = {"services": services}
    if volumes:
        document["volumes"] = volumes
    return ComposePlan(
        source="generated",
        yaml=yaml.safe_dump(document, sort_keys=False),
        services=plan_services,
    )


def _validate_service(name: str, service: dict[str, Any]) -> None:
    if service.get("privileged") is True:
        raise ComposeValidationError(f"Compose service {name} cannot be privileged.")
    if "container_name" in service:
        raise ComposeValidationError(f"Compose service {name} cannot set container_name.")
    if "network_mode" in service:
        raise ComposeValidationError(f"Compose service {name} cannot set network_mode.")
    if "networks" in service:
        raise ComposeValidationError(f"Compose service {name} cannot set custom networks.")
    if "env_file" in service:
        raise ComposeValidationError(f"Compose service {name} cannot use env_file.")
    volumes = service.get("volumes", [])
    if not isinstance(volumes, list):
        raise ComposeValidationError(f"Compose service {name} has an invalid volumes value.")
    for volume in volumes:
        _validate_volume(name, volume)


def _validate_volume(name: str, volume: object) -> None:
    if isinstance(volume, str):
        source = volume.split(":", 1)[0]
        if source.startswith(("/", ".", "~")) or "docker.sock" in source:
            raise ComposeValidationError(f"Compose service {name} cannot use a host bind mount.")
        return
    if isinstance(volume, dict):
        if volume.get("type") == "bind" or "source" not in volume:
            raise ComposeValidationError(f"Compose service {name} cannot use a host bind mount.")
        source = volume["source"]
        if not isinstance(source, str) or source.startswith(("/", ".", "~")):
            raise ComposeValidationError(f"Compose service {name} cannot use a host bind mount.")
        return
    raise ComposeValidationError(f"Compose service {name} has an invalid volume declaration.")


def _public_port(name: str, ports: object) -> int | None:
    if ports is None:
        return None
    if not isinstance(ports, list):
        raise ComposeValidationError(f"Compose service {name} has an invalid ports value.")
    if len(ports) > 1:
        raise ComposeValidationError(f"Compose service {name} may publish only one port.")
    if not ports:
        return None
    value = ports[0]
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        target = value.rsplit(":", 1)[-1].split("/", 1)[0]
    elif isinstance(value, dict):
        target = value.get("target")
    else:
        raise ComposeValidationError(f"Compose service {name} has an invalid port declaration.")
    try:
        port = int(target)
    except (TypeError, ValueError) as exc:
        raise ComposeValidationError(
            f"Compose service {name} must publish a numeric port."
        ) from exc
    if not 1 <= port <= 65535:
        raise ComposeValidationError(f"Compose service {name} has an invalid public port.")
    return port
