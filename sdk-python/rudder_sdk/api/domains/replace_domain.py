from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.domain_read import DomainRead
from ...models.domain_replace import DomainReplace
from ...models.error_envelope import ErrorEnvelope
from typing import cast
from uuid import UUID



def _get_kwargs(
    domain_id: UUID,
    *,
    body: DomainReplace,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}






    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/domains/{domain_id}".format(domain_id=quote(str(domain_id), safe=""),),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> DomainRead | ErrorEnvelope | None:
    if response.status_code == 200:
        response_200 = DomainRead.from_dict(response.json())



        return response_200

    if response.status_code == 403:
        response_403 = ErrorEnvelope.from_dict(response.json())



        return response_403

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


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[DomainRead | ErrorEnvelope]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    domain_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: DomainReplace,

) -> Response[DomainRead | ErrorEnvelope]:
    """ Replace a domain

     Sets every writable field. Idempotent. Refused with 403 on a system domain.

    Args:
        domain_id (UUID):
        body (DomainReplace): Body of ``PUT /domains/{id}``. Every writable field, always.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DomainRead | ErrorEnvelope]
     """


    kwargs = _get_kwargs(
        domain_id=domain_id,
body=body,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    domain_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: DomainReplace,

) -> DomainRead | ErrorEnvelope | None:
    """ Replace a domain

     Sets every writable field. Idempotent. Refused with 403 on a system domain.

    Args:
        domain_id (UUID):
        body (DomainReplace): Body of ``PUT /domains/{id}``. Every writable field, always.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DomainRead | ErrorEnvelope
     """


    return sync_detailed(
        domain_id=domain_id,
client=client,
body=body,

    ).parsed

async def asyncio_detailed(
    domain_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: DomainReplace,

) -> Response[DomainRead | ErrorEnvelope]:
    """ Replace a domain

     Sets every writable field. Idempotent. Refused with 403 on a system domain.

    Args:
        domain_id (UUID):
        body (DomainReplace): Body of ``PUT /domains/{id}``. Every writable field, always.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DomainRead | ErrorEnvelope]
     """


    kwargs = _get_kwargs(
        domain_id=domain_id,
body=body,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    domain_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: DomainReplace,

) -> DomainRead | ErrorEnvelope | None:
    """ Replace a domain

     Sets every writable field. Idempotent. Refused with 403 on a system domain.

    Args:
        domain_id (UUID):
        body (DomainReplace): Body of ``PUT /domains/{id}``. Every writable field, always.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DomainRead | ErrorEnvelope
     """


    return (await asyncio_detailed(
        domain_id=domain_id,
client=client,
body=body,

    )).parsed
