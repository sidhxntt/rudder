from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.http_validation_error import HTTPValidationError
from ...models.instance_read import InstanceRead
from typing import cast
from uuid import UUID



def _get_kwargs(
    service_id: UUID,

) -> dict[str, Any]:






    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/services/{service_id}/instances".format(service_id=quote(str(service_id), safe=""),),
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> HTTPValidationError | list[InstanceRead] | None:
    if response.status_code == 200:
        response_200 = []
        _response_200 = response.json()
        for response_200_item_data in (_response_200):
            response_200_item = InstanceRead.from_dict(response_200_item_data)



            response_200.append(response_200_item)

        return response_200

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())



        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[HTTPValidationError | list[InstanceRead]]:
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

) -> Response[HTTPValidationError | list[InstanceRead]]:
    """ Running containers for a service

     Instance is the fact, Deployment is the intent. A service is only actually serving if it has a
    healthy instance, which is what makes this distinct from the deployment status.

    Args:
        service_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | list[InstanceRead]]
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

) -> HTTPValidationError | list[InstanceRead] | None:
    """ Running containers for a service

     Instance is the fact, Deployment is the intent. A service is only actually serving if it has a
    healthy instance, which is what makes this distinct from the deployment status.

    Args:
        service_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | list[InstanceRead]
     """


    return sync_detailed(
        service_id=service_id,
client=client,

    ).parsed

async def asyncio_detailed(
    service_id: UUID,
    *,
    client: AuthenticatedClient | Client,

) -> Response[HTTPValidationError | list[InstanceRead]]:
    """ Running containers for a service

     Instance is the fact, Deployment is the intent. A service is only actually serving if it has a
    healthy instance, which is what makes this distinct from the deployment status.

    Args:
        service_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[HTTPValidationError | list[InstanceRead]]
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

) -> HTTPValidationError | list[InstanceRead] | None:
    """ Running containers for a service

     Instance is the fact, Deployment is the intent. A service is only actually serving if it has a
    healthy instance, which is what makes this distinct from the deployment status.

    Args:
        service_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        HTTPValidationError | list[InstanceRead]
     """


    return (await asyncio_detailed(
        service_id=service_id,
client=client,

    )).parsed
