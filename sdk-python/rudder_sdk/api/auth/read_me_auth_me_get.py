from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.error_body import ErrorBody
from ...models.http_validation_error import HTTPValidationError
from ...models.user_read import UserRead
from typing import cast



def _get_kwargs(

) -> dict[str, Any]:






    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/auth/me",
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> ErrorBody | HTTPValidationError | UserRead | None:
    if response.status_code == 200:
        response_200 = UserRead.from_dict(response.json())



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


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[ErrorBody | HTTPValidationError | UserRead]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient,

) -> Response[ErrorBody | HTTPValidationError | UserRead]:
    """ The authenticated user

     Who am I. Backs `rudder whoami` and the UI's session check on load.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorBody | HTTPValidationError | UserRead]
     """


    kwargs = _get_kwargs(

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    *,
    client: AuthenticatedClient,

) -> ErrorBody | HTTPValidationError | UserRead | None:
    """ The authenticated user

     Who am I. Backs `rudder whoami` and the UI's session check on load.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorBody | HTTPValidationError | UserRead
     """


    return sync_detailed(
        client=client,

    ).parsed

async def asyncio_detailed(
    *,
    client: AuthenticatedClient,

) -> Response[ErrorBody | HTTPValidationError | UserRead]:
    """ The authenticated user

     Who am I. Backs `rudder whoami` and the UI's session check on load.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorBody | HTTPValidationError | UserRead]
     """


    kwargs = _get_kwargs(

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    *,
    client: AuthenticatedClient,

) -> ErrorBody | HTTPValidationError | UserRead | None:
    """ The authenticated user

     Who am I. Backs `rudder whoami` and the UI's session check on load.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorBody | HTTPValidationError | UserRead
     """


    return (await asyncio_detailed(
        client=client,

    )).parsed
