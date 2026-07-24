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
ServiceRole = Literal[
    "web",
    "worker",
    "scheduler",
    "realtime",
    "database",
    "cache",
    "broker",
    "search",
    "storage",
    "observability",
    "other",
]


# Generated services are deliberately a small, audited catalog. Repository
# Compose is the escape hatch for any topology not represented here.
_CATALOG: dict[str, dict[str, Any]] = {
    "postgres": {
        "image": "postgres:16-alpine",
        "port": 5432,
        "role": "database",
        "volume": ("postgres-data", "/var/lib/postgresql/data"),
    },
    "mysql": {
        "image": "mysql:8",
        "port": 3306,
        "role": "database",
        "volume": ("mysql-data", "/var/lib/mysql"),
    },
    "mariadb": {
        "image": "mariadb:11",
        "port": 3306,
        "role": "database",
        "volume": ("mariadb-data", "/var/lib/mysql"),
    },
    "mongodb": {
        "image": "mongo:8",
        "port": 27017,
        "role": "database",
        "volume": ("mongodb-data", "/data/db"),
    },
    "redis": {
        "image": "redis:7-alpine",
        "port": 6379,
        "role": "cache",
        "volume": ("redis-data", "/data"),
    },
    "memcached": {"image": "memcached:1.6-alpine", "port": 11211, "role": "cache"},
    "rabbitmq": {
        "image": "rabbitmq:4-management-alpine",
        "port": 5672,
        "role": "broker",
        "volume": ("rabbitmq-data", "/var/lib/rabbitmq"),
    },
    "nats": {
        "image": "nats:2-alpine",
        "port": 4222,
        "role": "broker",
        "volume": ("nats-data", "/data"),
    },
    "meilisearch": {
        "image": "getmeili/meilisearch:v1.13",
        "port": 7700,
        "role": "search",
        "volume": ("meilisearch-data", "/meili_data"),
    },
    "typesense": {
        "image": "typesense/typesense:27.1",
        "port": 8108,
        "role": "search",
        "volume": ("typesense-data", "/data"),
    },
    "minio": {
        "image": "minio/minio:RELEASE.2025-04-22T22-12-26Z",
        "port": 9000,
        "role": "storage",
        "command": "server /data",
        "volume": ("minio-data", "/data"),
    },
    "qdrant": {
        "image": "qdrant/qdrant:v1.14.1",
        "port": 6333,
        "role": "search",
        "volume": ("qdrant-data", "/qdrant/storage"),
    },
    "prometheus": {
        "image": "prom/prometheus:v3.4.1",
        "port": 9090,
        "role": "observability",
        "volume": ("prometheus-data", "/prometheus"),
    },
    "grafana": {
        "image": "grafana/grafana:11.6.0",
        "port": 3000,
        "role": "observability",
        "volume": ("grafana-data", "/var/lib/grafana"),
    },
}


class ComposeValidationError(ValueError):
    """The repository Compose file asks for an unsafe host capability."""


@dataclass(frozen=True, slots=True)
class ComposeService:
    name: str
    public_port: int | None
    role: ServiceRole = "other"
    container_port: int | None = None

    @property
    def is_public(self) -> bool:
        return self.public_port is not None


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
        plan_services[name] = ComposeService(
            name=name,
            public_port=public_port,
            role=_service_role(name, service),
            container_port=_container_port(service, public_port),
        )

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
    unsupported = selected_addons - set(_CATALOG)
    if unsupported:
        names = ", ".join(sorted(unsupported))
        raise ComposeValidationError(f"Unsupported generated add-ons: {names}.")
    services: dict[str, dict[str, Any]] = {
        "app": {"build": ".", "expose": ["3000"]},
    }
    plan_services = {
        "app": ComposeService(name="app", public_port=3000, role="web", container_port=3000)
    }
    volumes: dict[str, dict[str, object]] = {}
    for addon in sorted(selected_addons):
        definition = _CATALOG[addon]
        service: dict[str, Any] = {
            "image": definition["image"],
            "expose": [str(definition["port"])],
        }
        if "command" in definition:
            service["command"] = definition["command"]
        volume = definition.get("volume")
        if volume is not None:
            volume_name, mount_path = volume
            service["volumes"] = [f"{volume_name}:{mount_path}"]
            volumes[volume_name] = {}
        services[addon] = service
        plan_services[addon] = ComposeService(
            name=addon,
            public_port=None,
            role=definition["role"],
            container_port=definition["port"],
        )
    document: dict[str, Any] = {"services": services}
    if volumes:
        document["volumes"] = volumes
    return ComposePlan(
        source="generated",
        yaml=yaml.safe_dump(document, sort_keys=False),
        services=plan_services,
    )


def supported_generated_addons() -> frozenset[str]:
    """Return the explicit names that Rudder can safely template."""
    return frozenset(_CATALOG)


def _service_role(name: str, service: dict[str, Any]) -> ServiceRole:
    """Classify only concrete Compose evidence; unknown services remain other."""
    lowered_name = name.lower()
    image = str(service.get("image", "")).lower()
    command = str(service.get("command", "")).lower()
    evidence = f"{lowered_name} {image} {command}"
    if any(token in evidence for token in ("worker", "sidekiq", "celery worker", "bullmq")):
        return "worker"
    if any(token in evidence for token in ("scheduler", "celery beat", "clock", "cron")):
        return "scheduler"
    if any(token in evidence for token in ("socket", "websocket", "realtime")):
        return "realtime"
    if any(token in evidence for token in ("postgres", "mysql", "mariadb", "mongo")):
        return "database"
    if any(token in evidence for token in ("redis", "memcached")):
        return "cache"
    if any(token in evidence for token in ("rabbitmq", "nats", "kafka", "activemq")):
        return "broker"
    if any(
        token in evidence
        for token in (
            "meilisearch",
            "typesense",
            "elasticsearch",
            "opensearch",
            "qdrant",
            "weaviate",
            "milvus",
        )
    ):
        return "search"
    if any(token in evidence for token in ("minio", "s3")):
        return "storage"
    if any(token in evidence for token in ("prometheus", "grafana", "loki", "tempo")):
        return "observability"
    if service.get("ports") or lowered_name in {"web", "app", "api", "frontend", "backend"}:
        return "web"
    return "other"


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


def _container_port(service: dict[str, Any], public_port: int | None) -> int | None:
    """Return the first internal exposed port for UI/runtime metadata."""
    expose = service.get("expose")
    if isinstance(expose, (str, int)):
        expose = [expose]
    if isinstance(expose, list) and expose:
        value = str(expose[0]).split("/", 1)[0]
        try:
            port = int(value)
        except ValueError:
            port = None
        if port is not None and 1 <= port <= 65535:
            return port
    return public_port
