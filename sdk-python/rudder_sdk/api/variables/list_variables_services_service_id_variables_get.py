from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.http_validation_error import HTTPValidationError
from ...models.variable_read import VariableRead
from typing import cast
from uuid import UUID



def _get_kwargs(
    service_id: UUID,

) -> dict[str, Any]:






    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/services/{service_id}/variables".format(service_id=quote(str(service_id), safe=""),),
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> HTTPValidationError | list[VariableRead] | None:
    if response.status_code == 200:
        response_200 = []
        _response_200 = response.json()
        for response_200_item_data in (_response_200):
            response_200_item = VariableRead.from_dict(response_200_item_data)



            response_200.append(response_200_item)

        return response_200

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())



        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[HTTPValidationError | list[VariableRead]]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    service_id: UUID,
    *,
    client: AuthenticatedClient | Client,

) -> Response[HTTPValidationError | list[VariableRead]]:
    """ List a service's variables

     Keys, reference flags and timestamps. Values are never returned.

    Args:
        service_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | list[VariableRead]]
     """


    kwargs = _get_kwargs(
        service_id=service_id,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    service_id: UUID,
    *,
    client: AuthenticatedClient | Client,

) -> HTTPValidationError | list[VariableRead] | None:
    """ List a service's variables

     Keys, reference flags and timestamps. Values are never returned.

    Args:
        service_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | list[VariableRead]
     """


    return sync_detailed(
        service_id=service_id,
client=client,

    ).parsed

async def asyncio_detailed(
    service_id: UUID,
    *,
    client: AuthenticatedClient | Client,

) -> Response[HTTPValidationError | list[VariableRead]]:
    """ List a service's variables

     Keys, reference flags and timestamps. Values are never returned.

    Args:
        service_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | list[VariableRead]]
     """


    kwargs = _get_kwargs(
        service_id=service_id,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    service_id: UUID,
    *,
    client: AuthenticatedClient | Client,

) -> HTTPValidationError | list[VariableRead] | None:
    """ List a service's variables

     Keys, reference flags and timestamps. Values are never returned.

    Args:
        service_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | list[VariableRead]
     """


    return (await asyncio_detailed(
        service_id=service_id,
client=client,

    )).parsed
