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


@dataclass(frozen=True, slots=True)
class GitHubInstallation:
    id: int
    account_login: str
    repository_selection: str


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

    async def installations(self) -> list[GitHubInstallation]:
        """List accounts where this Rudder App is installed."""
        payload = await self._app_get("/app/installations")
        return [
            GitHubInstallation(
                id=int(installation["id"]),
                account_login=str(installation["account"]["login"]),
                repository_selection=str(installation["repository_selection"]),
            )
            for installation in payload
        ]

    async def branches(self, installation_id: int, repo: str) -> list[str]:
        payload = await self._get(installation_id, f"/repos/{repo}/branches")
        return [str(branch["name"]) for branch in payload]

    async def package_json(self, installation_id: int, repo: str, branch: str) -> dict[str, Any]:
        content = await self.file_at_ref(installation_id, repo, branch, "package.json")
        if content is None:
            raise GitHubAppError("Repository has no valid package.json on this branch.")
        try:
            import json

            return json.loads(content)
        except ValueError as exc:
            raise GitHubAppError("Repository has no valid package.json on this branch.") from exc

    async def file_at_ref(
        self, installation_id: int, repo: str, branch: str, path: str
    ) -> str | None:
        """Return one UTF-8 repository file, or ``None`` when it is absent."""
        payload = await self._get_optional(
            installation_id, f"/repos/{repo}/contents/{path}?ref={branch}"
        )
        if payload is None:
            return None
        try:
            return base64.b64decode(str(payload["content"])).decode()
        except (KeyError, ValueError, UnicodeDecodeError) as exc:
            raise GitHubAppError(f"Repository file {path} is not valid UTF-8 content.") from exc

    async def installation_token(self, installation_id: int) -> str:
        """Mint a short-lived installation token for a source checkout."""
        return await self._installation_token(installation_id)

    async def comment_on_pull_request(
        self, installation_id: int, repo: str, number: int, body: str
    ) -> None:
        """Post the stable environment URL through the installation token."""
        token = await self._installation_token(installation_id)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        async with httpx.AsyncClient(base_url="https://api.github.com", headers=headers) as client:
            response = await client.post(
                f"/repos/{repo}/issues/{number}/comments", json={"body": body}
            )
        if response.status_code >= 400:
            raise GitHubAppError(
                f"Could not comment on pull request: GitHub returned {response.status_code}."
            )

    async def _get(self, installation_id: int, path: str) -> Any:
        token = await self._installation_token(installation_id)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        async with httpx.AsyncClient(base_url="https://api.github.com", headers=headers) as client:
            response = await client.get(path)
        if response.status_code >= 400:
            raise GitHubAppError(f"GitHub returned {response.status_code}: {response.text[:200]}")
        return response.json()

    async def _get_optional(self, installation_id: int, path: str) -> Any | None:
        token = await self._installation_token(installation_id)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
        async with httpx.AsyncClient(base_url="https://api.github.com", headers=headers) as client:
            response = await client.get(path)
        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise GitHubAppError(f"GitHub returned {response.status_code}: {response.text[:200]}")
        return response.json()

    async def _installation_token(self, installation_id: int) -> str:
        if not self.configured:
            raise GitHubAppError("GitHub App credentials are not configured.")
        app_jwt = self._app_jwt()
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

    def _app_jwt(self) -> str:
        if not self.configured:
            raise GitHubAppError("GitHub App credentials are not configured.")
        now = int(time.time())
        key = self._settings.resolved_github_app_private_key.replace("\\n", "\n")
        return jwt.encode(
            {"iat": now - 60, "exp": now + 540, "iss": self._settings.github_app_id},
            key,
            algorithm="RS256",
        )

    async def _app_get(self, path: str) -> Any:
        headers = {
            "Authorization": f"Bearer {self._app_jwt()}",
            "Accept": "application/vnd.github+json",
        }
        async with httpx.AsyncClient(base_url="https://api.github.com", headers=headers) as client:
            response = await client.get(path)
        if response.status_code >= 400:
            raise GitHubAppError("Could not list GitHub App installations.")
        return response.json()
