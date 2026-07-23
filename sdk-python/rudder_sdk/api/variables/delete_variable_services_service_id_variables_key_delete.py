from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.http_validation_error import HTTPValidationError
from typing import cast
from uuid import UUID



def _get_kwargs(
    service_id: UUID,
    key: str,

) -> dict[str, Any]:






    _kwargs: dict[str, Any] = {
        "method": "delete",
        "url": "/services/{service_id}/variables/{key}".format(service_id=quote(str(service_id), safe=""),key=quote(str(key), safe=""),),
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Any | HTTPValidationError | None:
    if response.status_code == 204:
        response_204 = cast(Any, None)
        return response_204

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())



        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[Any | HTTPValidationError]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    service_id: UUID,
    key: str,
    *,
    client: AuthenticatedClient | Client,

) -> Response[Any | HTTPValidationError]:
    """ Delete a variable

     204 when it is gone, 404 when it was never there.

    Args:
        service_id (UUID):
        key (str): Env var name, e.g. DATABASE_URL.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
     """


    kwargs = _get_kwargs(
        service_id=service_id,
key=key,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    service_id: UUID,
    key: str,
    *,
    client: AuthenticatedClient | Client,

) -> Any | HTTPValidationError | None:
    """ Delete a variable

     204 when it is gone, 404 when it was never there.

    Args:
        service_id (UUID):
        key (str): Env var name, e.g. DATABASE_URL.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
     """


    return sync_detailed(
        service_id=service_id,
key=key,
client=client,

    ).parsed

async def asyncio_detailed(
    service_id: UUID,
    key: str,
    *,
    client: AuthenticatedClient | Client,

) -> Response[Any | HTTPValidationError]:
    """ Delete a variable

     204 when it is gone, 404 when it was never there.

    Args:
        service_id (UUID):
        key (str): Env var name, e.g. DATABASE_URL.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
     """


    kwargs = _get_kwargs(
        service_id=service_id,
key=key,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    service_id: UUID,
    key: str,
    *,
    client: AuthenticatedClient | Client,

) -> Any | HTTPValidationError | None:
    """ Delete a variable

     204 when it is gone, 404 when it was never there.

    Args:
        service_id (UUID):
        key (str): Env var name, e.g. DATABASE_URL.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
     """


    return (await asyncio_detailed(
        service_id=service_id,
key=key,
client=client,

    )).parsed
