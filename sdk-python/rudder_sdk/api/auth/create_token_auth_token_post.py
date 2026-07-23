from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.error_body import ErrorBody
from ...models.http_validation_error import HTTPValidationError
from ...models.login_request import LoginRequest
from ...models.token_response import TokenResponse
from typing import cast



def _get_kwargs(
    *,
    body: LoginRequest,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}






    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/auth/token",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> ErrorBody | HTTPValidationError | TokenResponse | None:
    if response.status_code == 200:
        response_200 = TokenResponse.from_dict(response.json())



        return response_200

    if response.status_code == 401:
        response_401 = ErrorBody.from_dict(response.json())



        return response_401

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())



        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[ErrorBody | HTTPValidationError | TokenResponse]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: LoginRequest,

) -> Response[ErrorBody | HTTPValidationError | TokenResponse]:
    """ Exchange credentials for an access token

     Log in. Returns the token for header clients and sets it as a cookie for the UI.

    Resource-oriented per the PRD: the token is the resource and logging in
    creates one, so this is ``POST /auth/token``, not ``POST /auth/login``.

    Args:
        body (LoginRequest): Credentials for ``POST /auth/token``.

            ``email`` is a plain ``str``, not ``EmailStr``: pydantic's email validator is
            a separate package that is not in ``pyproject.toml``, and there is exactly
            one user whose address came from ``.env`` — validating its format here would
            buy nothing and add a dependency.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorBody | HTTPValidationError | TokenResponse]
     """


    kwargs = _get_kwargs(
        body=body,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    *,
    client: AuthenticatedClient | Client,
    body: LoginRequest,

) -> ErrorBody | HTTPValidationError | TokenResponse | None:
    """ Exchange credentials for an access token

     Log in. Returns the token for header clients and sets it as a cookie for the UI.

    Resource-oriented per the PRD: the token is the resource and logging in
    creates one, so this is ``POST /auth/token``, not ``POST /auth/login``.

    Args:
        body (LoginRequest): Credentials for ``POST /auth/token``.

            ``email`` is a plain ``str``, not ``EmailStr``: pydantic's email validator is
            a separate package that is not in ``pyproject.toml``, and there is exactly
            one user whose address came from ``.env`` — validating its format here would
            buy nothing and add a dependency.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorBody | HTTPValidationError | TokenResponse
     """


    return sync_detailed(
        client=client,
body=body,

    ).parsed

async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: LoginRequest,

) -> Response[ErrorBody | HTTPValidationError | TokenResponse]:
    """ Exchange credentials for an access token

     Log in. Returns the token for header clients and sets it as a cookie for the UI.

    Resource-oriented per the PRD: the token is the resource and logging in
    creates one, so this is ``POST /auth/token``, not ``POST /auth/login``.

    Args:
        body (LoginRequest): Credentials for ``POST /auth/token``.

            ``email`` is a plain ``str``, not ``EmailStr``: pydantic's email validator is
            a separate package that is not in ``pyproject.toml``, and there is exactly
            one user whose address came from ``.env`` — validating its format here would
            buy nothing and add a dependency.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorBody | HTTPValidationError | TokenResponse]
     """


    kwargs = _get_kwargs(
        body=body,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    *,
    client: AuthenticatedClient | Client,
    body: LoginRequest,

) -> ErrorBody | HTTPValidationError | TokenResponse | None:
    """ Exchange credentials for an access token

     Log in. Returns the token for header clients and sets it as a cookie for the UI.

    Resource-oriented per the PRD: the token is the resource and logging in
    creates one, so this is ``POST /auth/token``, not ``POST /auth/login``.

    Args:
        body (LoginRequest): Credentials for ``POST /auth/token``.

            ``email`` is a plain ``str``, not ``EmailStr``: pydantic's email validator is
            a separate package that is not in ``pyproject.toml``, and there is exactly
            one user whose address came from ``.env`` — validating its format here would
            buy nothing and add a dependency.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorBody | HTTPValidationError | TokenResponse
     """


    return (await asyncio_detailed(
        client=client,
body=body,

    )).parsed
