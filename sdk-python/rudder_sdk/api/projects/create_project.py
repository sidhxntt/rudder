from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.error_envelope import ErrorEnvelope
from ...models.project_create import ProjectCreate
from ...models.project_read import ProjectRead
from typing import cast



def _get_kwargs(
    *,
    body: ProjectCreate,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}






    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/projects",
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> ErrorEnvelope | ProjectRead | None:
    if response.status_code == 201:
        response_201 = ProjectRead.from_dict(response.json())



        return response_201

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


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[ErrorEnvelope | ProjectRead]:
    return Response(
        status_code=HTTPStatus(response.status_code),
        content=response.content,
        headers=response.headers,
        parsed=_parse_response(client=client, response=response),
    )


def sync_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: ProjectCreate,

) -> Response[ErrorEnvelope | ProjectRead]:
    """ Create a project

     Creates the project and its `production` environment. Returns the full project resource.

    Args:
        body (ProjectCreate): Body of ``POST /projects``.

            Creating a project also creates its ``production`` environment — a project
            with no environment cannot hold a service, and every phase document assumes
            ``production`` exists.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorEnvelope | ProjectRead]
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
    body: ProjectCreate,

) -> ErrorEnvelope | ProjectRead | None:
    """ Create a project

     Creates the project and its `production` environment. Returns the full project resource.

    Args:
        body (ProjectCreate): Body of ``POST /projects``.

            Creating a project also creates its ``production`` environment — a project
            with no environment cannot hold a service, and every phase document assumes
            ``production`` exists.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorEnvelope | ProjectRead
     """


    return sync_detailed(
        client=client,
body=body,

    ).parsed

async def asyncio_detailed(
    *,
    client: AuthenticatedClient | Client,
    body: ProjectCreate,

) -> Response[ErrorEnvelope | ProjectRead]:
    """ Create a project

     Creates the project and its `production` environment. Returns the full project resource.

    Args:
        body (ProjectCreate): Body of ``POST /projects``.

            Creating a project also creates its ``production`` environment — a project
            with no environment cannot hold a service, and every phase document assumes
            ``production`` exists.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorEnvelope | ProjectRead]
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
    body: ProjectCreate,

) -> ErrorEnvelope | ProjectRead | None:
    """ Create a project

     Creates the project and its `production` environment. Returns the full project resource.

    Args:
        body (ProjectCreate): Body of ``POST /projects``.

            Creating a project also creates its ``production`` environment — a project
            with no environment cannot hold a service, and every phase document assumes
            ``production`` exists.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorEnvelope | ProjectRead
     """


    return (await asyncio_detailed(
        client=client,
body=body,

    )).parsed
