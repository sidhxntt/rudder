"""Auth endpoints and the ``get_current_user`` dependency every other router uses.

Phase 1 step 3 asks for a decision on where the token lives. **Both, with the
``Authorization: Bearer`` header authoritative.**

- The header is the contract. It is the only thing the CLI, the Python SDK, and
  the TS SDK send, and Phase 1's acceptance test is the full create-deploy-logs
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
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlmodel import Session

from rudder_cp.config import Settings, get_settings
from rudder_cp.db import get_session
from rudder_cp.models import User
from rudder_cp.schemas.auth import ErrorBody, LoginRequest, TokenResponse, UserRead
from rudder_cp.services import auth as auth_service
from rudder_cp.services.github_oauth import GitHubOAuthClient, GitHubOAuthError

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
) -> RedirectResponse:
    try:
        identity = await GitHubOAuthClient(request.app.state.settings).exchange(code, state)
    except GitHubOAuthError as exc:
        raise ApiError(status.HTTP_401_UNAUTHORIZED, "github_oauth_failed", str(exc)) from exc
    user = await auth_service.find_or_create_github_user(
        session, github_id=identity.id, login=identity.login, email=identity.email
    )
    issued = auth_service.issue_token(user.id)
    response = RedirectResponse("/", status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    _set_session_cookie(response, issued.token, issued.expires_in, request.app.state.settings)
    return response


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
