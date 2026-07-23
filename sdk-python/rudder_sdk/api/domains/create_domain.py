from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.domain_create import DomainCreate
from ...models.domain_read import DomainRead
from ...models.error_envelope import ErrorEnvelope
from typing import cast
from uuid import UUID



def _get_kwargs(
    environment_id: UUID,
    *,
    body: DomainCreate,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}






    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/environments/{environment_id}/domains".format(environment_id=quote(str(environment_id), safe=""),),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> DomainRead | ErrorEnvelope | None:
    if response.status_code == 201:
        response_201 = DomainRead.from_dict(response.json())



        return response_201

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
    environment_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: DomainCreate,

) -> Response[DomainRead | ErrorEnvelope]:
    """ Create a domain in an environment

     Exactly one of `service_id` / `deployment_id` must be set, matching `target_type`; anything else is
    a 422. A hostname already in use — including by a system domain — is a 409. The created domain is
    never a system domain.

    Args:
        environment_id (UUID):
        body (DomainCreate): Body of ``POST /environments/{environment_id}/domains``.

            There is no ``is_system`` field. System domains are created by the control
            plane alongside their service and cannot be forged through this API.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DomainRead | ErrorEnvelope]
     """


    kwargs = _get_kwargs(
        environment_id=environment_id,
body=body,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    environment_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: DomainCreate,

) -> DomainRead | ErrorEnvelope | None:
    """ Create a domain in an environment

     Exactly one of `service_id` / `deployment_id` must be set, matching `target_type`; anything else is
    a 422. A hostname already in use — including by a system domain — is a 409. The created domain is
    never a system domain.

    Args:
        environment_id (UUID):
        body (DomainCreate): Body of ``POST /environments/{environment_id}/domains``.

            There is no ``is_system`` field. System domains are created by the control
            plane alongside their service and cannot be forged through this API.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DomainRead | ErrorEnvelope
     """


    return sync_detailed(
        environment_id=environment_id,
client=client,
body=body,

    ).parsed

async def asyncio_detailed(
    environment_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: DomainCreate,

) -> Response[DomainRead | ErrorEnvelope]:
    """ Create a domain in an environment

     Exactly one of `service_id` / `deployment_id` must be set, matching `target_type`; anything else is
    a 422. A hostname already in use — including by a system domain — is a 409. The created domain is
    never a system domain.

    Args:
        environment_id (UUID):
        body (DomainCreate): Body of ``POST /environments/{environment_id}/domains``.

            There is no ``is_system`` field. System domains are created by the control
            plane alongside their service and cannot be forged through this API.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DomainRead | ErrorEnvelope]
     """


    kwargs = _get_kwargs(
        environment_id=environment_id,
body=body,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    environment_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: DomainCreate,

) -> DomainRead | ErrorEnvelope | None:
    """ Create a domain in an environment

     Exactly one of `service_id` / `deployment_id` must be set, matching `target_type`; anything else is
    a 422. A hostname already in use — including by a system domain — is a 409. The created domain is
    never a system domain.

    Args:
        environment_id (UUID):
        body (DomainCreate): Body of ``POST /environments/{environment_id}/domains``.

            There is no ``is_system`` field. System domains are created by the control
            plane alongside their service and cannot be forged through this API.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DomainRead | ErrorEnvelope
     """


    return (await asyncio_detailed(
        environment_id=environment_id,
client=client,
body=body,

    )).parsed
