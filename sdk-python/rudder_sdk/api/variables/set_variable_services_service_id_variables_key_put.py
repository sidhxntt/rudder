from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.variable_read import VariableRead
from ...models.variable_upsert import VariableUpsert
from typing import cast
from uuid import UUID



def _get_kwargs(
    service_id: UUID,
    key: str,
    *,
    body: VariableUpsert,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}






    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/services/{service_id}/variables/{key}".format(service_id=quote(str(service_id), safe=""),key=quote(str(key), safe=""),),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> VariableRead | None:
    if response.status_code == 200:
        response_200 = VariableRead.from_dict(response.json())



        return response_200

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[VariableRead]:
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
    body: VariableUpsert,

) -> Response[VariableRead]:
    """ Set a variable (idempotent)

     Create or replace one variable. The response omits the value by design.

    Args:
        service_id (UUID):
        key (str): Env var name, e.g. DATABASE_URL.
        body (VariableUpsert): Body of ``PUT /services/{service_id}/variables/{key}``.

            Only the value. The key is in the path (that is what makes the PUT
            idempotent and addressable) and ``is_reference`` is derived from the value by
            the service layer, never asserted by the client.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[VariableRead]
     """


    kwargs = _get_kwargs(
        service_id=service_id,
key=key,
body=body,

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
    body: VariableUpsert,

) -> VariableRead | None:
    """ Set a variable (idempotent)

     Create or replace one variable. The response omits the value by design.

    Args:
        service_id (UUID):
        key (str): Env var name, e.g. DATABASE_URL.
        body (VariableUpsert): Body of ``PUT /services/{service_id}/variables/{key}``.

            Only the value. The key is in the path (that is what makes the PUT
            idempotent and addressable) and ``is_reference`` is derived from the value by
            the service layer, never asserted by the client.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        VariableRead
     """


    return sync_detailed(
        service_id=service_id,
key=key,
client=client,
body=body,

    ).parsed

async def asyncio_detailed(
    service_id: UUID,
    key: str,
    *,
    client: AuthenticatedClient | Client,
    body: VariableUpsert,

) -> Response[VariableRead]:
    """ Set a variable (idempotent)

     Create or replace one variable. The response omits the value by design.

    Args:
        service_id (UUID):
        key (str): Env var name, e.g. DATABASE_URL.
        body (VariableUpsert): Body of ``PUT /services/{service_id}/variables/{key}``.

            Only the value. The key is in the path (that is what makes the PUT
            idempotent and addressable) and ``is_reference`` is derived from the value by
            the service layer, never asserted by the client.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[VariableRead]
     """


    kwargs = _get_kwargs(
        service_id=service_id,
key=key,
body=body,

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
    body: VariableUpsert,

) -> VariableRead | None:
    """ Set a variable (idempotent)

     Create or replace one variable. The response omits the value by design.

    Args:
        service_id (UUID):
        key (str): Env var name, e.g. DATABASE_URL.
        body (VariableUpsert): Body of ``PUT /services/{service_id}/variables/{key}``.

            Only the value. The key is in the path (that is what makes the PUT
            idempotent and addressable) and ``is_reference`` is derived from the value by
            the service layer, never asserted by the client.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        VariableRead
     """


    return (await asyncio_detailed(
        service_id=service_id,
key=key,
client=client,
body=body,

    )).parsed
