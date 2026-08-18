"""Canonical Kubernetes namespace derivation for environment-scoped workloads."""

from __future__ import annotations

from uuid import UUID

from rudder_cp.config import Settings


def environment_namespace(settings: Settings, environment_id: UUID) -> str:
    """Return the environment's stable, isolated Kubernetes namespace name."""
    return f"{settings.kubernetes_namespace_prefix}-{environment_id.hex[:12]}"
