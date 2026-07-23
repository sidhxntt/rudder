from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.error_envelope import ErrorEnvelope
from ...models.service_read import ServiceRead
from ...models.service_update import ServiceUpdate
from typing import cast
from uuid import UUID



def _get_kwargs(
    service_id: UUID,
    *,
    body: ServiceUpdate,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}






    _kwargs: dict[str, Any] = {
        "method": "patch",
        "url": "/services/{service_id}".format(service_id=quote(str(service_id), safe=""),),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> ErrorEnvelope | ServiceRead | None:
    if response.status_code == 200:
        response_200 = ServiceRead.from_dict(response.json())



        return response_200

    if response.status_code == 404:
        response_404 = ErrorEnvelope.from_dict(response.json())



        return response_404

    if response.status_code == 409:
        response_409 = ErrorEnvelope.from_dict(response.json())



        return response_409

    if response.status_code == 422:
        response_422 = ErrorEnvelope.from_dict(response.json())



        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[ErrorEnvelope | ServiceRead]:
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
    body: ServiceUpdate,

) -> Response[ErrorEnvelope | ServiceRead]:
    """ Partially update a service

     Fields left out are untouched. Renaming rewrites the system domain hostname. `canvas_x` / `canvas_y`
    are UI metadata (D6): they persist and trigger nothing.

    Args:
        service_id (UUID):
        body (ServiceUpdate): Body of ``PATCH /services/{id}``. Absent fields are left alone.

            Renaming rewrites the service's system domain hostname. Moving the node on
            the canvas (``canvas_x`` / ``canvas_y``) is pure metadata per D6 — it
            persists and triggers nothing.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorEnvelope | ServiceRead]
     """


    kwargs = _get_kwargs(
        service_id=service_id,
body=body,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    service_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: ServiceUpdate,

) -> ErrorEnvelope | ServiceRead | None:
    """ Partially update a service

     Fields left out are untouched. Renaming rewrites the system domain hostname. `canvas_x` / `canvas_y`
    are UI metadata (D6): they persist and trigger nothing.

    Args:
        service_id (UUID):
        body (ServiceUpdate): Body of ``PATCH /services/{id}``. Absent fields are left alone.

            Renaming rewrites the service's system domain hostname. Moving the node on
            the canvas (``canvas_x`` / ``canvas_y``) is pure metadata per D6 — it
            persists and triggers nothing.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorEnvelope | ServiceRead
     """


    return sync_detailed(
        service_id=service_id,
client=client,
body=body,

    ).parsed

async def asyncio_detailed(
    service_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: ServiceUpdate,

) -> Response[ErrorEnvelope | ServiceRead]:
    """ Partially update a service

     Fields left out are untouched. Renaming rewrites the system domain hostname. `canvas_x` / `canvas_y`
    are UI metadata (D6): they persist and trigger nothing.

    Args:
        service_id (UUID):
        body (ServiceUpdate): Body of ``PATCH /services/{id}``. Absent fields are left alone.

            Renaming rewrites the service's system domain hostname. Moving the node on
            the canvas (``canvas_x`` / ``canvas_y``) is pure metadata per D6 — it
            persists and triggers nothing.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorEnvelope | ServiceRead]
     """


    kwargs = _get_kwargs(
        service_id=service_id,
body=body,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    service_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: ServiceUpdate,

) -> ErrorEnvelope | ServiceRead | None:
    """ Partially update a service

     Fields left out are untouched. Renaming rewrites the system domain hostname. `canvas_x` / `canvas_y`
    are UI metadata (D6): they persist and trigger nothing.

    Args:
        service_id (UUID):
        body (ServiceUpdate): Body of ``PATCH /services/{id}``. Absent fields are left alone.

            Renaming rewrites the service's system domain hostname. Moving the node on
            the canvas (``canvas_x`` / ``canvas_y``) is pure metadata per D6 — it
            persists and triggers nothing.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorEnvelope | ServiceRead
     """


    return (await asyncio_detailed(
        service_id=service_id,
client=client,
body=body,

    )).parsed
