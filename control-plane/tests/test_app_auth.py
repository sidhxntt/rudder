"""Every route on the real app is either authenticated or deliberately public.

This exists because the routers were built in parallel with auth and every one
of them shipped with `# TODO(auth)`. The result was an API where
`POST /services/{id}/deploy` — which clones a git repo and runs it — answered
202 to anyone who could reach the port.

The test walks the actual app rather than a hand-written list, so a new router
added without protection fails here instead of shipping open.
"""

from collections.abc import Iterator
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from rudder_cp.config import get_settings
from rudder_cp.db import get_session
from rudder_cp.main import create_app
from rudder_cp.services.github_oauth import GitHubIdentity, GitHubOAuthClient

# Endpoints that must stay reachable without a token, each for a stated reason.
PUBLIC = {
    ("POST", "/auth/token"),  # issues the token; cannot require one
    ("DELETE", "/auth/token"),  # logout must work with an expired token
    ("POST", "/webhooks/github"),  # authenticated by HMAC over the body
    ("POST", "/nodes/register"),  # authenticated by shared secret
    ("POST", "/nodes/heartbeat"),  # authenticated by shared secret
    ("GET", "/healthz"),  # liveness probe
    ("GET", "/docs"),
    ("GET", "/redoc"),
    ("GET", "/openapi.json"),
    ("GET", "/docs/oauth2-redirect"),
}

_SAMPLE_UUID = "00000000-0000-0000-0000-000000000000"


@pytest.fixture(name="client")
def client_fixture(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)

    def session_override() -> Iterator[Session]:
        with Session(engine) as session:
            yield session

    monkeypatch.setenv("RUDDER_SECRET_KEYS", "")
    monkeypatch.setenv("RUDDER_JWT_SECRET", "test-only-signing-secret")
    # Settings are cached process-wide. Refresh after monkeypatching and clean
    # up afterward so this app fixture neither inherits nor leaks configuration.
    get_settings.cache_clear()
    try:
        app = create_app()
        app.dependency_overrides[get_session] = session_override
        # Not entering the lifespan: it starts the deploy worker and seeds a user,
        # neither of which this test needs. Routing is fully configured without it.
        yield TestClient(app)
    finally:
        get_settings.cache_clear()


def _routes(client: TestClient) -> list[tuple[str, str]]:
    """Read the routes off the OpenAPI schema.

    Walking `app.routes` does NOT work: this FastAPI version keeps included
    routers as opaque wrapper objects with no `path` or `methods`, so that walk
    finds only the five routes declared directly on the app — and every
    assertion built on it passes while testing nothing.
    """
    schema = client.app.openapi()  # type: ignore[attr-defined]
    return [
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        for method in operations
        if method.upper() not in {"HEAD", "OPTIONS"}
    ]


def test_the_app_exposes_routes_at_all(client: TestClient) -> None:
    """Guards the walker itself — a listing bug would make every other
    assertion here vacuously true."""
    assert len(_routes(client)) > 20


def test_no_resource_route_answers_without_a_token(client: TestClient) -> None:
    open_routes: list[tuple[str, str]] = []

    for method, path in _routes(client):
        if (method, path) in PUBLIC:
            continue
        url = path
        for placeholder in ("{project_id}", "{environment_id}", "{service_id}", "{domain_id}"):
            url = url.replace(placeholder, _SAMPLE_UUID)
        url = url.replace("{deployment_id}", _SAMPLE_UUID).replace("{key}", "SOME_KEY")

        response = client.request(method, url, json={})
        # 401 is the goal. 405 would mean the walker built a bad request.
        if response.status_code != 401:
            open_routes.append((method, path, response.status_code))  # type: ignore[arg-type]

    assert not open_routes, f"routes reachable without authentication: {open_routes}"


def test_a_garbage_token_is_rejected(client: TestClient) -> None:
    response = client.get("/projects", headers={"Authorization": "Bearer not-a-jwt"})
    assert response.status_code == 401


def test_public_routes_stay_public(client: TestClient) -> None:
    """A blanket dependency is easy to over-apply. Logout in particular must
    work when the token has already expired."""
    assert client.get("/healthz").status_code == 200
    assert client.delete("/auth/token").status_code < 400
    # Wrong password, not missing auth: proves the endpoint was reached.
    assert client.post("/auth/token", json={"email": "a@b.c", "password": "x"}).status_code == 401


def test_healthz_reports_the_selected_runtime(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["runtime"] == "docker"


def test_github_oauth_start_redirects_to_github(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = client.app.state.settings  # type: ignore[attr-defined]
    settings.github_oauth_client_id = "client-id"
    settings.github_oauth_client_secret = "client-secret"
    settings.github_oauth_redirect_uri = "http://localhost:8000/auth/github/callback"
    response = client.get("/auth/github/start", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"].startswith("https://github.com/login/oauth/authorize?")
    query = parse_qs(urlparse(response.headers["location"]).query)
    assert query["scope"] == ["user:email"]


@pytest.mark.asyncio
async def test_github_oauth_exchange_uses_the_verified_primary_email(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = client.app.state.settings  # type: ignore[attr-defined]
    settings.github_oauth_client_id = "client-id"
    settings.github_oauth_client_secret = "client-secret"
    settings.github_oauth_redirect_uri = "http://localhost:8000/auth/github/callback"
    oauth = GitHubOAuthClient(settings)
    state = parse_qs(urlparse(oauth.authorization_url()).query)["state"][0]

    class Response:
        def __init__(self, payload: object) -> None:
            self._payload = payload
            self.is_error = False

        def json(self) -> object:
            return self._payload

    class Client:
        async def __aenter__(self) -> "Client":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

        async def post(self, *_args: object, **_kwargs: object) -> Response:
            return Response({"access_token": "token"})

        async def get(self, url: str, **_kwargs: object) -> Response:
            if url.endswith("/user"):
                return Response(
                    {
                        "id": 1234,
                        "login": "octocat",
                        "email": None,
                        "avatar_url": "https://avatars.githubusercontent.com/u/1234",
                    }
                )
            return Response(
                [
                    {"email": "secondary@example.test", "primary": False, "verified": True},
                    {"email": "owner@example.test", "primary": True, "verified": True},
                ]
            )

    monkeypatch.setattr(
        "rudder_cp.services.github_oauth.httpx.AsyncClient", lambda **_kwargs: Client()
    )

    identity = await oauth.exchange("code", state)

    assert identity.email == "owner@example.test"
    assert identity.avatar_url == "https://avatars.githubusercontent.com/u/1234"


async def _identity(_self: GitHubOAuthClient, _code: str, _state: str) -> GitHubIdentity:
    return GitHubIdentity(id=1234, login="octocat", email="octocat@github.test")


def test_github_oauth_callback_opens_the_dashboard_import_flow(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(GitHubOAuthClient, "exchange", _identity)
    response = client.get("/auth/github/callback?code=valid&state=valid", follow_redirects=False)
    assert response.status_code == 307
    assert response.headers["location"] == "http://localhost:3000/dashboard?import=github"
    assert "rudder_token=" in response.headers["set-cookie"]
