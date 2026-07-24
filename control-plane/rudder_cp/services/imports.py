"""Repository inspection and add-on proposals for GitHub imports.

Detection is intentionally manifest-based. A dependency shows that an add-on is
plausible; the user still confirms provisioning before Rudder creates anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


POSTGRES_CLIENTS = frozenset({"pg", "@prisma/client", "prisma", "sequelize"})
REDIS_CLIENTS = frozenset({"redis", "ioredis"})


@dataclass(frozen=True, slots=True)
class AddonProposal:
    """The safe, reviewable result of inspecting one Node ``package.json``."""

    is_node_app: bool
    addons: tuple[str, ...]
    externally_managed: tuple[str, ...]


def detect_node_addons(
    package_json: dict[str, Any], *, existing_variable_keys: set[str]
) -> AddonProposal:
    """Return confirmable Postgres/Redis candidates from a package manifest.

    An existing connection variable always wins over package inference: Rudder
    must not replace a deliberately configured external database or cache.
    """
    dependencies = _dependencies(package_json)
    is_node_app = "express" in dependencies
    addons: list[str] = []
    externally_managed: list[str] = []

    if dependencies & POSTGRES_CLIENTS:
        _propose_or_mark_external(
            addon="postgres",
            variable_key="DATABASE_URL",
            existing_variable_keys=existing_variable_keys,
            addons=addons,
            externally_managed=externally_managed,
        )
    if dependencies & REDIS_CLIENTS:
        _propose_or_mark_external(
            addon="redis",
            variable_key="REDIS_URL",
            existing_variable_keys=existing_variable_keys,
            addons=addons,
            externally_managed=externally_managed,
        )

    return AddonProposal(
        is_node_app=is_node_app,
        addons=tuple(addons),
        externally_managed=tuple(externally_managed),
    )


def _dependencies(package_json: dict[str, Any]) -> set[str]:
    combined: set[str] = set()
    for key in ("dependencies", "devDependencies"):
        values = package_json.get(key)
        if isinstance(values, dict):
            combined.update(name for name, version in values.items() if isinstance(version, str))
    return combined


def _propose_or_mark_external(
    *,
    addon: str,
    variable_key: str,
    existing_variable_keys: set[str],
    addons: list[str],
    externally_managed: list[str],
) -> None:
    if variable_key in existing_variable_keys:
        externally_managed.append(addon)
    else:
        addons.append(addon)
