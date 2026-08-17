"""Server-side GitHub OAuth authorization-code client."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
import jwt

from rudder_cp.config import Settings
from rudder_cp.security import JWT_ALGORITHM

_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
_TOKEN_URL = "https://github.com/login/oauth/access_token"
_PROFILE_URL = "https://api.github.com/user"
_EMAILS_URL = "https://api.github.com/user/emails"
_STATE_AUDIENCE = "github-oauth-state"
_RETRYABLE_GITHUB_STATUS_CODES = frozenset({429, 502, 503, 504})


class GitHubOAuthError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class GitHubIdentity:
    id: int
    login: str
    email: str | None
    avatar_url: str | None = None


def _verified_primary_email(payload: object) -> str | None:
    """Return only GitHub's verified primary email from the OAuth API response."""
    if not isinstance(payload, list):
        return None
    for item in payload:
        if not isinstance(item, dict):
            continue
        email = item.get("email")
        if (
            item.get("primary") is True
            and item.get("verified") is True
            and isinstance(email, str)
            and email.strip()
        ):
            return email.strip()
    return None


async def _get_with_retry(
    client: httpx.AsyncClient, url: str, *, headers: dict[str, str]
) -> httpx.Response:
    """Retry brief GitHub API outages during the OAuth callback.

    The authorization code has already been exchanged at this point. A
    temporary 503 from either identity endpoint should not make a user restart
    the complete browser OAuth flow.
    """
    response = await client.get(url, headers=headers)
    for attempt in range(2):
        if getattr(response, "status_code", None) not in _RETRYABLE_GITHUB_STATUS_CODES:
            return response
        await asyncio.sleep(0.25 * (attempt + 1))
        response = await client.get(url, headers=headers)
    return response


class GitHubOAuthClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _require_config(self) -> None:
        configured = (
            self.settings.github_oauth_client_id,
            self.settings.github_oauth_client_secret,
            self.settings.github_oauth_redirect_uri,
            self.settings.jwt_secret,
        )
        if not all(configured):
            raise GitHubOAuthError("GitHub OAuth is not configured.")

    def authorization_url(self) -> str:
        self._require_config()
        now = datetime.now(UTC)
        state = jwt.encode(
            {"aud": _STATE_AUDIENCE, "iat": now, "exp": now + timedelta(minutes=10)},
            self.settings.jwt_secret,
            algorithm=JWT_ALGORITHM,
        )
        query = urlencode(
            {
                "client_id": self.settings.github_oauth_client_id,
                "redirect_uri": self.settings.github_oauth_redirect_uri,
                "scope": "user:email",
                "state": state,
            }
        )
        return f"{_AUTHORIZE_URL}?{query}"

    async def exchange(self, code: str, state: str) -> GitHubIdentity:
        self._require_config()
        try:
            jwt.decode(
                state,
                self.settings.jwt_secret,
                algorithms=[JWT_ALGORITHM],
                audience=_STATE_AUDIENCE,
                options={"require": ["aud", "exp"]},
            )
        except jwt.PyJWTError as exc:
            raise GitHubOAuthError("GitHub OAuth state is invalid or expired.") from exc
        async with httpx.AsyncClient(timeout=10.0) as client:
            token = await client.post(
                _TOKEN_URL,
                headers={"Accept": "application/json"},
                json={
                    "client_id": self.settings.github_oauth_client_id,
                    "client_secret": self.settings.github_oauth_client_secret,
                    "code": code,
                    "redirect_uri": self.settings.github_oauth_redirect_uri,
                },
            )
            if token.is_error or not token.json().get("access_token"):
                raise GitHubOAuthError("GitHub declined the authorization code.")
            headers = {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token.json()['access_token']}",
            }
            profile = await _get_with_retry(
                client,
                _PROFILE_URL,
                headers=headers,
            )
            emails = await _get_with_retry(
                client,
                _EMAILS_URL,
                headers=headers,
            )
        if profile.is_error:
            raise GitHubOAuthError("GitHub profile lookup failed.")
        if emails.is_error:
            raise GitHubOAuthError("GitHub verified email lookup failed.")
        value = profile.json()
        if not isinstance(value.get("id"), int) or not isinstance(value.get("login"), str):
            raise GitHubOAuthError("GitHub returned an incomplete profile.")
        avatar_url = value.get("avatar_url")
        return GitHubIdentity(
            id=value["id"],
            login=value["login"],
            email=_verified_primary_email(emails.json()),
            # Do not manufacture arbitrary URLs: only pass through GitHub's
            # optional profile field, and use the initial fallback otherwise.
            avatar_url=avatar_url if isinstance(avatar_url, str) and avatar_url else None,
        )
