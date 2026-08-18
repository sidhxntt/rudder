# ruff: noqa: E501
"""Auth endpoints and the ``get_current_user`` dependency every other router uses.

Phase 1 step 3 asks for a decision on where the token lives. **Both, with the
``Authorization: Bearer`` header authoritative.**

- The header is the contract. It is the only thing the Node CLI and other API
  clients send, and Phase 1's acceptance test is the full create-deploy-logs
  cycle with no browser open. Anything the header cannot do is a bug.
- The cookie is an additive convenience for ``web/``. ``POST /auth/token``
  *also* sets an httpOnly ``rudder_token`` cookie so the Next.js app never has
  to put a JWT in ``localStorage``, where any XSS can read it. The cookie is
  read only as a fallback when no header is present.

Why not one or the other: header-only forces the browser to store the token in
JS-reachable storage; cookie-only would need CSRF machinery and makes `curl`
sessions awkward. Supporting both costs one `or` in one function, and no
endpoint is reachable by cookie alone — so the CLI path is always the exercised
path.

CSRF: the cookie is ``SameSite=Lax``, so a third-party origin cannot drive a
state-changing request with it. ``localhost:3000 -> localhost:8000`` is
same-site (ports are not part of a site), so the dev UI is unaffected. There is
no CSRF token because there is no sessions table and no cookie-only route.

Not built, on purpose: refresh tokens, a sessions/revocation table, roles,
permissions, signup. A logged-in operator holds one short-lived JWT; logging out
clears the cookie and the client drops the token.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from rudder_cp.config import Settings, get_settings
from rudder_cp.db import get_session
from rudder_cp.models import User
from rudder_cp.schemas.auth import (
    AuthorizationStartResponse,
    ErrorBody,
    LoginRequest,
    TokenResponse,
    UserRead,
)
from rudder_cp.services import auth as auth_service
from rudder_cp.services.authorization_handoff import (
    AuthorizationHandoffError,
    AuthorizationHandoffs,
)
from rudder_cp.services.github_oauth import (
    GitHubOAuthClient,
    GitHubOAuthConfigurationError,
    GitHubOAuthError,
)

SESSION_COOKIE = "rudder_token"

# One message for "no such email" and for "wrong password". Anything that
# differs between the two is an account-enumeration oracle.
_GENERIC_LOGIN_FAILURE = "Invalid email or password"

router = APIRouter(prefix="/auth", tags=["auth"])

# auto_error=False so a missing header falls through to the cookie instead of
# HTTPBearer raising its own non-uniform 403 before we ever look.
_bearer_scheme = HTTPBearer(auto_error=False, description="Bearer <access_token>")


class ApiError(HTTPException):
    """An HTTPException that serialises to the PRD's uniform ``{code, message, details}``.

    FastAPI's default handler wraps ``detail`` in ``{"detail": ...}``, which is
    not the documented shape, so ``api_error_handler`` below replaces it.

    Lives here because auth is the first workstream to need it; move it to a
    shared ``rudder_cp/errors.py`` when one exists.
    """

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.body = ErrorBody(code=code, message=message, details=dict(details or {}))
        super().__init__(status_code=status_code, detail=message, headers=headers)


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Render an ``ApiError`` as ``{code, message, details}``.

    Register it in ``main.py``::

        app.add_exception_handler(ApiError, api_error_handler)
    """
    if not isinstance(exc, ApiError):  # pragma: no cover - registration guard
        raise exc
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.body.model_dump(),
        headers=exc.headers,
    )


def _not_authenticated(message: str = "Authentication required") -> ApiError:
    return ApiError(
        status.HTTP_401_UNAUTHORIZED,
        "not_authenticated",
        message,
        headers={"WWW-Authenticate": "Bearer"},
    )


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
BearerDep = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)]
CookieDep = Annotated[str | None, Cookie(alias=SESSION_COOKIE, include_in_schema=False)]


async def get_current_user(
    session: SessionDep,
    credentials: BearerDep = None,
    cookie_token: CookieDep = None,
) -> User:
    """Resolve the caller's token to the single user, or raise a uniform 401.

    Header first, cookie second. Protect an endpoint with::

        from rudder_cp.routers.auth import CurrentUser

        @router.get("/projects")
        async def list_projects(user: CurrentUser) -> list[ProjectRead]: ...
    """
    token = credentials.credentials if credentials is not None else cookie_token
    if not token:
        raise _not_authenticated()
    try:
        return await auth_service.user_for_token(session, token)
    except auth_service.InvalidToken as exc:
        # Deliberately does not say whether the token was malformed, expired, or
        # signed with a rotated key.
        raise _not_authenticated("Invalid or expired token") from exc


CurrentUser = Annotated[User, Depends(get_current_user)]


def _set_session_cookie(response: Response, token: str, max_age: int, settings: Settings) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        # D8: dev runs plain HTTP on *.localhost, where a Secure cookie is never
        # sent. Tie the flag to the TLS mode rather than hardcoding either way.
        secure=settings.tls_mode == "acme",
        path="/",
    )


@router.post(
    "/token",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Exchange credentials for an access token",
    responses={401: {"model": ErrorBody, "description": "Invalid email or password"}},
)
async def create_token(
    payload: LoginRequest,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> TokenResponse:
    """Log in. Returns the token for header clients and sets it as a cookie for the UI.

    Resource-oriented per the PRD: the token is the resource and logging in
    creates one, so this is ``POST /auth/token``, not ``POST /auth/login``.
    """
    try:
        _, issued = await auth_service.login(session, payload.email, payload.password)
    except auth_service.InvalidCredentials as exc:
        raise ApiError(
            status.HTTP_401_UNAUTHORIZED,
            "invalid_credentials",
            _GENERIC_LOGIN_FAILURE,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    expires_in = issued.expires_in
    _set_session_cookie(response, issued.token, expires_in, settings)
    return TokenResponse(access_token=issued.token, expires_in=expires_in)


@router.post(
    "/authorizations",
    response_model=AuthorizationStartResponse,
    status_code=status.HTTP_201_CREATED,
    responses={503: {"model": ErrorBody, "description": "GitHub OAuth unavailable"}},
)
async def create_authorization(
    session: SessionDep, settings: SettingsDep
) -> AuthorizationStartResponse:
    """Create a short-lived browser authorization handoff."""
    oauth = GitHubOAuthClient(settings)
    try:
        oauth.ensure_configured()
    except GitHubOAuthConfigurationError as exc:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE, "github_oauth_unavailable", str(exc)
        ) from exc
    authorization_id = AuthorizationHandoffs(session).create()
    authorization = oauth.authorization(authorization_id=authorization_id)
    return AuthorizationStartResponse(
        id=authorization_id,
        authorization_url=authorization.authorization_url,
        state=authorization.state,
    )


@router.post(
    "/authorizations/{authorization_id}/consume",
    response_model=TokenResponse,
    responses={
        202: {"description": "Authorization is pending"},
        401: {"model": ErrorBody, "description": "Authorization is invalid or consumed"},
    },
)
async def consume_authorization(
    authorization_id: str, session: SessionDep, settings: SettingsDep
) -> TokenResponse | Response:
    """Consume an authorized handoff exactly once, or report that it is pending."""
    try:
        token = AuthorizationHandoffs(session).consume(authorization_id)
    except AuthorizationHandoffError as exc:
        raise _not_authenticated(
            "Authorization request is invalid, expired, or already consumed."
        ) from exc
    if token is None:
        return Response(status_code=status.HTTP_202_ACCEPTED)
    return TokenResponse(access_token=token, expires_in=settings.jwt_ttl_seconds)


@router.get("/github/start", include_in_schema=False)
async def github_start(request: Request) -> RedirectResponse:
    try:
        return RedirectResponse(GitHubOAuthClient(request.app.state.settings).authorization_url())
    except GitHubOAuthError as exc:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE, "github_oauth_unavailable", str(exc)
        ) from exc


@router.get("/github/callback", include_in_schema=False)
async def github_callback(
    request: Request, code: str, state: str, session: SessionDep
) -> Response:
    oauth = GitHubOAuthClient(request.app.state.settings)
    try:
        authorization_id = oauth.authorization_id_for_state(state)
        identity = await oauth.exchange(code, state)
    except GitHubOAuthConfigurationError as exc:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE, "github_oauth_unavailable", str(exc)
        ) from exc
    except GitHubOAuthError as exc:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "github_oauth_failed", str(exc)) from exc
    user = await auth_service.find_or_create_github_user(
        session,
        github_id=identity.id,
        login=identity.login,
        email=identity.email,
        avatar_url=identity.avatar_url,
    )
    issued = auth_service.issue_token(user.id)
    if authorization_id is not None:
        try:
            AuthorizationHandoffs(session).complete(authorization_id, issued.token)
        except AuthorizationHandoffError as exc:
            raise _not_authenticated(
                "Authorization request is invalid, expired, or already consumed."
            ) from exc
        return HTMLResponse(_authorization_complete_page())
    response = RedirectResponse(
        f"{request.app.state.settings.web_url.rstrip('/')}/dashboard?import=github",
        status_code=status.HTTP_307_TEMPORARY_REDIRECT,
    )
    _set_session_cookie(response, issued.token, issued.expires_in, request.app.state.settings)
    return response


def _authorization_complete_page() -> str:
    """Render the safe, token-free completion surface for a terminal handoff."""
    return """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Authorization complete · Rudder</title>
    <style>
      :root { --rd-accent:#3ecf8e; --rd-accent-deep:#24b47e; --rd-surface:#1c1c1c; --rd-surface-raised:#242424; --rd-surface-inset:#171717; --rd-hairline:#2e2e2e; --rd-text:#ededed; --rd-text-secondary:#b2b2b2; --rd-text-mute:#9a9a9a; }
      * { box-sizing:border-box; }
      html { background:var(--rd-surface); color:var(--rd-text); font-family:Inter,"Helvetica Neue",Helvetica,Arial,sans-serif; }
      body { min-height:100vh; margin:0; background:var(--rd-surface); }
      .shell { width:min(100% - 40px, 1240px); margin:0 auto; }
      nav { display:flex; align-items:center; justify-content:space-between; min-height:92px; border-bottom:1px solid var(--rd-hairline); }
      .brand { display:inline-flex; align-items:center; gap:10px; font-size:16px; font-weight:600; letter-spacing:-.03em; }
      .mark { display:grid; width:32px; height:32px; place-items:center; border:1px solid color-mix(in srgb,var(--rd-accent) 62%,transparent); border-radius:8px; background:color-mix(in srgb,var(--rd-accent) 10%,transparent); }
      .mark i { width:8px; height:8px; border-radius:50%; background:var(--rd-accent); box-shadow:0 0 16px rgba(62,207,142,.8); }
      .tag { border:1px solid #3a3a3a; border-radius:4px; padding:5px 9px; color:var(--rd-text-mute); font:12px ui-monospace,SFMono-Regular,Menlo,monospace; }
      main { display:grid; grid-template-columns:minmax(0,.9fr) minmax(420px,1.1fr); gap:80px; align-items:center; min-height:calc(100vh - 93px); padding:88px 42px; }
      h1 { max-width:650px; margin:0; font-size:clamp(3.5rem,7vw,6.25rem); font-weight:500; line-height:.91; letter-spacing:-.055em; }
      p { max-width:530px; margin:32px 0 0; color:var(--rd-text-secondary); font-size:18px; line-height:1.55; }
      button { min-height:44px; margin-top:32px; padding:0 18px; border:0; border-radius:6px; background:var(--rd-accent); color:#171717; cursor:pointer; font:600 14px Inter,"Helvetica Neue",Helvetica,Arial,sans-serif; transition:background-color 140ms ease,transform 140ms ease; }
      button:hover { background:var(--rd-accent-deep); transform:translateY(-1px); }
      button:focus-visible { outline:2px solid var(--rd-accent); outline-offset:3px; }
      .hint { margin-top:14px; color:var(--rd-text-mute); font-size:13px; }
      .panel { overflow:hidden; border:1px solid var(--rd-hairline); background:#141916; box-shadow:0 28px 90px rgba(0,0,0,.42); }
      .panel-head { display:flex; justify-content:space-between; border-bottom:1px solid var(--rd-hairline); padding:18px 22px; color:var(--rd-text-mute); font:11px ui-monospace,SFMono-Regular,Menlo,monospace; letter-spacing:.12em; text-transform:uppercase; }
      .live { color:var(--rd-accent); }
      .content { padding:38px 40px; }
      .state { display:flex; align-items:center; gap:12px; font-size:22px; font-weight:500; letter-spacing:-.025em; }
      .state-dot { width:9px; height:9px; border-radius:50%; background:var(--rd-accent); box-shadow:0 0 16px rgba(62,207,142,.75); }
      .line { height:1px; margin:32px 0; background:var(--rd-hairline); }
      .terminal { padding:18px; background:var(--rd-surface-inset); border:1px solid var(--rd-hairline); color:var(--rd-text-secondary); font:13px/1.8 ui-monospace,SFMono-Regular,Menlo,monospace; }
      .terminal strong { color:var(--rd-accent); font-weight:500; }
      .footer { display:flex; justify-content:space-between; gap:16px; color:var(--rd-text-mute); font-size:13px; }
      @media (max-width:850px) { .shell { width:min(100% - 32px, 650px); } nav { min-height:72px; } .tag { display:none; } main { display:block; min-height:auto; padding:72px 0; } h1 { font-size:clamp(3.25rem,15vw,5.2rem); } .panel { margin-top:64px; } .content { padding:28px 22px; } }
    </style>
  </head>
  <body>
    <div class="shell">
      <nav aria-label="Rudder authorization">
        <div class="brand"><span class="mark" aria-hidden="true"><i></i></span><span>rudder</span></div>
        <span class="tag">CLI sign-in</span>
      </nav>
      <main>
        <section aria-labelledby="complete-title">
          <h1 id="complete-title">Your terminal is connected.</h1>
          <p>GitHub authorization is complete. Rudder has securely returned your session to the CLI—nothing is stored in this browser page.</p>
          <button type="button" onclick="window.close()">Return to your terminal</button>
          <div class="hint">You can close this tab if your browser does not close it automatically.</div>
        </section>
        <section class="panel" aria-label="CLI authorization status">
          <div class="panel-head"><span>authorization handoff</span><span class="live">● live</span></div>
          <div class="content">
            <div class="state"><span class="state-dot" aria-hidden="true"></span><span>GitHub connected</span></div>
            <div class="line"></div>
            <div class="terminal"><strong>✓</strong> identity verified<br><strong>✓</strong> terminal session delivered<br><span style="color:#9a9a9a">next</span> return to <strong>rudder</strong> in your terminal</div>
            <div class="line"></div>
            <div class="footer"><span>single-use handoff</span><span>session ready</span></div>
          </div>
        </section>
      </main>
    </div>
  </body>
</html>"""


@router.delete(
    "/token",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Log out",
)
async def delete_token(response: Response, settings: SettingsDep) -> None:
    """Clear the session cookie.

    Unauthenticated on purpose: logging out must work when the token is already
    expired, and there is nothing server-side to revoke. Header clients simply
    discard the token — this endpoint exists for the browser.
    """
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        httponly=True,
        samesite="lax",
        secure=settings.tls_mode == "acme",
    )


@router.get(
    "/me",
    response_model=UserRead,
    summary="The authenticated user",
    responses={401: {"model": ErrorBody, "description": "Missing or invalid token"}},
)
async def read_me(user: CurrentUser) -> UserRead:
    """Who am I. Backs `rudder whoami` and the UI's session check on load."""
    return UserRead.model_validate(user)
