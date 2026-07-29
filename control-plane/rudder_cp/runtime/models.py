"""Runtime-neutral, immutable values used by Kubernetes releases."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

_DNS_LABEL = re.compile(r"[^a-z0-9-]+")
_DASHES = re.compile(r"-+")


def dns_label(value: str, *, max_length: int = 63) -> str:
    """Return a non-empty Kubernetes DNS label without guessing ownership."""
    normalized = _DASHES.sub("-", _DNS_LABEL.sub("-", value.lower())).strip("-")
    if not normalized:
        raise ValueError("Kubernetes resource name has no DNS-safe characters.")
    return normalized[:max_length].rstrip("-")


@dataclass(frozen=True, slots=True)
class ComposeService:
    """One reviewed Compose member after image and variables are resolved."""

    name: str
    image: str
    port: int | None = None
    command: tuple[str, ...] | None = None
    environment: Mapping[str, str] = field(default_factory=dict)
    public: bool = False
    # The reviewed Rudder domain is canonical.  When present, the runtime must
    # expose this hostname instead of inventing a release-local alternative.
    public_host: str | None = None
    stateful: bool = False
    volume_mount_path: str | None = None
    # Set only by Rudder's trusted managed-service catalog.  A repository
    # Compose member called "postgres" is still just a user-owned container;
    # it must never be silently transformed into an operator-managed database.
    managed_database_engine: str | None = None
    # A validated snapshot of ServiceOperationsState.desired.  It is attached
    # to the release instead of read by this runtime so Kubernetes rendering
    # remains deterministic for an immutable deployment candidate.
    operations: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class KubernetesRelease:
    """The immutable candidate Kubernetes release for one Rudder deployment."""

    namespace: str
    release_id: str
    services: tuple[ComposeService, ...]

    def resource_name(self, service_name: str) -> str:
        suffix = dns_label(self.release_id)[:8]
        prefix_limit = 63 - len(suffix) - 1
        return f"{dns_label(service_name, max_length=prefix_limit)}-{suffix}"
