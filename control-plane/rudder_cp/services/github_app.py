"""Minimal GitHub App client for installation-scoped repository imports."""

from __future__ import annotations

import base64
import time
from dataclasses import dataclass
from typing import Any

import httpx
import jwt

from rudder_cp.config import Settings


class GitHubAppError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GitHubRepository:
    full_name: str
    default_branch: str
    private: bool


class GitHubAppClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def configured(self) -> bool:
        return self._settings.github_app_configured

    async def repositories(self, installation_id: int) -> list[GitHubRepository]:
        payload = await self._get(installation_id, "/installation/repositories")
        return [
            GitHubRepository(
                full_name=str(repo["full_name"]),
                default_branch=str(repo["default_branch"]),
                private=bool(repo["private"]),
            )
            for repo in payload.get("repositories", [])
        ]

    async def branches(self, installation_id: int, repo: str) -> list[str]:
        payload = await self._get(installation_id, f"/repos/{repo}/branches")
        return [str(branch["name"]) for branch in payload]

    async def package_json(self, installation_id: int, repo: str, branch: str) -> dict[str, Any]:
        payload = await self._get(
            installation_id, f"/repos/{repo}/contents/package.json?ref={branch}"
        )
        try:
            import json

            return json.loads(base64.b64decode(str(payload["content"])).decode())
        except (KeyError, ValueError, UnicodeDecodeError) as exc:
            raise GitHubAppError("Repository has no valid package.json on this branch.") from exc

    async def _get(self, installation_id: int, path: str) -> Any:
        token = await self._installation_token(installation_id)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        async with httpx.AsyncClient(base_url="https://api.github.com", headers=headers) as client:
            response = await client.get(path)
        if response.status_code >= 400:
            raise GitHubAppError(f"GitHub returned {response.status_code}: {response.text[:200]}")
        return response.json()

    async def _installation_token(self, installation_id: int) -> str:
        if not self.configured:
            raise GitHubAppError("GitHub App credentials are not configured.")
        now = int(time.time())
        key = self._settings.github_app_private_key.replace("\\n", "\n")
        app_jwt = jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": self._settings.github_app_id},
            key,
            algorithm="RS256",
        )
        async with httpx.AsyncClient(base_url="https://api.github.com") as client:
            response = await client.post(
                f"/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {app_jwt}",
                    "Accept": "application/vnd.github+json",
                },
            )
        if response.status_code >= 400:
            raise GitHubAppError("Could not authorize this GitHub App installation.")
        return str(response.json()["token"])
