"""On-disk state: the access token and the selected project/environment/service.

Two files, both under ``$RUDDER_CONFIG_DIR`` (default ``$XDG_CONFIG_HOME/rudder``,
default ``~/.config/rudder``), directory mode 0700, files mode 0600:

``credentials.json``
    ``{"base_url", "access_token", "expires_at"}``. Written by ``rudder login``.
    The token is a bearer credential, so it lives in a file only the user can
    read — never in an env var the CLI prints, never on a command line where the
    shell would record it in history.

``context.json``
    ``{"project", "environment", "service"}``, each an ``{"id", "name"}`` pair.
    This is what lets ``rudder deploy api`` name a service the API addresses by
    UUID. See ``context.py``.

Names are cached alongside ids purely so ``rudder status`` can print them
without an extra round trip. The id is what is used; a stale cached name is
cosmetic, and every resolve path re-reads names from the API.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "http://localhost:8000"

_CREDENTIALS_FILE = "credentials.json"
_CONTEXT_FILE = "context.json"


def config_dir() -> Path:
    """Where CLI state lives. Honours RUDDER_CONFIG_DIR, then XDG."""
    override = os.environ.get("RUDDER_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg).expanduser() if xdg else Path.home() / ".config"
    return base / "rudder"


def _read_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        return {}
    try:
        loaded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    """Write 0600, creating the 0700 directory. Never widens an existing mode."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    os.replace(tmp, path)
    os.chmod(path, 0o600)


@dataclass(slots=True)
class Credentials:
    base_url: str = DEFAULT_BASE_URL
    access_token: str | None = None
    expires_at: float | None = None  # unix seconds, best-effort hint only

    @classmethod
    def load(cls) -> Credentials:
        data = _read_json(config_dir() / _CREDENTIALS_FILE)
        return cls(
            base_url=str(data.get("base_url") or DEFAULT_BASE_URL),
            access_token=data.get("access_token") or None,
            expires_at=data.get("expires_at"),
        )

    def save(self) -> Path:
        path = config_dir() / _CREDENTIALS_FILE
        _write_private_json(
            path,
            {
                "base_url": self.base_url,
                "access_token": self.access_token,
                "expires_at": self.expires_at,
            },
        )
        return path

    @staticmethod
    def clear() -> None:
        (config_dir() / _CREDENTIALS_FILE).unlink(missing_ok=True)


@dataclass(slots=True)
class Selection:
    """A remembered resource: the id is authoritative, the name is a label."""

    id: str
    name: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name}

    @classmethod
    def from_dict(cls, data: Any) -> Selection | None:
        if not isinstance(data, dict):
            return None
        rid, name = data.get("id"), data.get("name")
        if not isinstance(rid, str) or not isinstance(name, str):
            return None
        return cls(id=rid, name=name)


@dataclass(slots=True)
class Context:
    project: Selection | None = None
    environment: Selection | None = None
    service: Selection | None = None

    @classmethod
    def load(cls) -> Context:
        data = _read_json(config_dir() / _CONTEXT_FILE)
        return cls(
            project=Selection.from_dict(data.get("project")),
            environment=Selection.from_dict(data.get("environment")),
            service=Selection.from_dict(data.get("service")),
        )

    def save(self) -> Path:
        path = config_dir() / _CONTEXT_FILE
        _write_private_json(
            path,
            {
                "project": self.project.to_dict() if self.project else None,
                "environment": self.environment.to_dict() if self.environment else None,
                "service": self.service.to_dict() if self.service else None,
            },
        )
        return path
