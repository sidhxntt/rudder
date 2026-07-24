"""Evidence-based application process detection for repository imports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ProcessRole = Literal["web", "worker", "scheduler", "realtime"]


@dataclass(frozen=True, slots=True)
class ProcessProposal:
    """A user-reviewable process command found in a manifest or Procfile."""

    role: ProcessRole
    command: str
    source: Literal["procfile", "package_json"]


_PROCFILE_ROLES: dict[str, ProcessRole] = {
    "web": "web",
    "worker": "worker",
    "clock": "scheduler",
    "scheduler": "scheduler",
    "realtime": "realtime",
}
_SCRIPT_ROLES: dict[str, ProcessRole] = {
    "start": "web",
    "serve": "web",
    "dev": "web",
    "worker": "worker",
    "queue": "worker",
    "start:worker": "worker",
    "start:queue": "worker",
    "scheduler": "scheduler",
    "cron": "scheduler",
    "start:cron": "scheduler",
    "realtime": "realtime",
    "socket": "realtime",
}


def detect_processes(
    package_json: dict[str, Any], procfile: str | None
) -> tuple[ProcessProposal, ...]:
    """Return at most one explicit command for each supported process role.

    A Procfile is the repository's stronger declaration and takes precedence
    over generic package scripts. Unknown commands are deliberately ignored.
    """
    detected: dict[ProcessRole, ProcessProposal] = {}
    if procfile:
        for line in procfile.splitlines():
            name, separator, command = line.partition(":")
            role = _PROCFILE_ROLES.get(name.strip().lower())
            normalized_command = command.strip()
            if separator and role and normalized_command:
                detected[role] = ProcessProposal(role, normalized_command, "procfile")

    scripts = package_json.get("scripts")
    if isinstance(scripts, dict):
        for name, command in scripts.items():
            role = _SCRIPT_ROLES.get(name) if isinstance(name, str) else None
            if (
                role is None
                or role in detected
                or not isinstance(command, str)
                or not command.strip()
            ):
                continue
            detected[role] = ProcessProposal(role, f"npm run {name}", "package_json")

    return tuple(
        detected[role]
        for role in ("web", "worker", "scheduler", "realtime")
        if role in detected
    )
