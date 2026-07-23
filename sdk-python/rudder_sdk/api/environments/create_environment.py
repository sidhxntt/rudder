from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.environment_create import EnvironmentCreate
from ...models.environment_read import EnvironmentRead
from ...models.error_envelope import ErrorEnvelope
from typing import cast
from uuid import UUID



def _get_kwargs(
    project_id: UUID,
    *,
    body: EnvironmentCreate,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}






    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/projects/{project_id}/environments".format(project_id=quote(str(project_id), safe=""),),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> EnvironmentRead | ErrorEnvelope | None:
    if response.status_code == 201:
        response_201 = EnvironmentRead.from_dict(response.json())



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


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[EnvironmentRead | ErrorEnvelope]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    project_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: EnvironmentCreate,

) -> Response[EnvironmentRead | ErrorEnvelope]:
    """ Create an environment in a project

     Allocates a dedicated /24 for the environment's WireGuard mesh at create time — it is never assigned
    later, because renumbering an existing mesh is not an option.

    Args:
        project_id (UUID):
        body (EnvironmentCreate): Body of ``POST /projects/{project_id}/environments``.

            ``wg_subnet`` is not accepted from the client: it is a server-allocated
            resource (see ``services.environments.allocate_wg_subnet``).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvironmentRead | ErrorEnvelope]
     """


    kwargs = _get_kwargs(
        project_id=project_id,
body=body,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    project_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: EnvironmentCreate,

) -> EnvironmentRead | ErrorEnvelope | None:
    """ Create an environment in a project

     Allocates a dedicated /24 for the environment's WireGuard mesh at create time — it is never assigned
    later, because renumbering an existing mesh is not an option.

    Args:
        project_id (UUID):
        body (EnvironmentCreate): Body of ``POST /projects/{project_id}/environments``.

            ``wg_subnet`` is not accepted from the client: it is a server-allocated
            resource (see ``services.environments.allocate_wg_subnet``).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvironmentRead | ErrorEnvelope
     """


    return sync_detailed(
        project_id=project_id,
client=client,
body=body,

    ).parsed

async def asyncio_detailed(
    project_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: EnvironmentCreate,

) -> Response[EnvironmentRead | ErrorEnvelope]:
    """ Create an environment in a project

     Allocates a dedicated /24 for the environment's WireGuard mesh at create time — it is never assigned
    later, because renumbering an existing mesh is not an option.

    Args:
        project_id (UUID):
        body (EnvironmentCreate): Body of ``POST /projects/{project_id}/environments``.

            ``wg_subnet`` is not accepted from the client: it is a server-allocated
            resource (see ``services.environments.allocate_wg_subnet``).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvironmentRead | ErrorEnvelope]
     """


    kwargs = _get_kwargs(
        project_id=project_id,
body=body,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    project_id: UUID,
    *,
    client: AuthenticatedClient | Client,
    body: EnvironmentCreate,

) -> EnvironmentRead | ErrorEnvelope | None:
    """ Create an environment in a project

     Allocates a dedicated /24 for the environment's WireGuard mesh at create time — it is never assigned
    later, because renumbering an existing mesh is not an option.

    Args:
        project_id (UUID):
        body (EnvironmentCreate): Body of ``POST /projects/{project_id}/environments``.

            ``wg_subnet`` is not accepted from the client: it is a server-allocated
            resource (see ``services.environments.allocate_wg_subnet``).

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvironmentRead | ErrorEnvelope
     """


    return (await asyncio_detailed(
        project_id=project_id,
client=client,
body=body,

    )).parsed
