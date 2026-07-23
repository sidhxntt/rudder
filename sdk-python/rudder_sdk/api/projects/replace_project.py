from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.error_envelope import ErrorEnvelope
from ...models.project_read import ProjectRead
from ...models.project_replace import ProjectReplace
from typing import cast
from uuid import UUID



def _get_kwargs(
    project_id: UUID,
    *,
    body: ProjectReplace,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}






    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/projects/{project_id}".format(project_id=quote(str(project_id), safe=""),),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> ErrorEnvelope | ProjectRead | None:
    if response.status_code == 200:
        response_200 = ProjectRead.from_dict(response.json())



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


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[ErrorEnvelope | ProjectRead]:
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
    body: ProjectReplace,

) -> Response[ErrorEnvelope | ProjectRead]:
    """ Replace a project

     Sets every writable field. Idempotent: the same body twice yields the same resource.

    Args:
        project_id (UUID):
        body (ProjectReplace): Body of ``PUT /projects/{id}``. Every writable field, always.

            ``owner_id`` and ``created_at`` are server-owned and are not writable, so a
            PUT of the same body twice is genuinely the same result.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorEnvelope | ProjectRead]
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
    body: ProjectReplace,

) -> ErrorEnvelope | ProjectRead | None:
    """ Replace a project

     Sets every writable field. Idempotent: the same body twice yields the same resource.

    Args:
        project_id (UUID):
        body (ProjectReplace): Body of ``PUT /projects/{id}``. Every writable field, always.

            ``owner_id`` and ``created_at`` are server-owned and are not writable, so a
            PUT of the same body twice is genuinely the same result.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorEnvelope | ProjectRead
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
    body: ProjectReplace,

) -> Response[ErrorEnvelope | ProjectRead]:
    """ Replace a project

     Sets every writable field. Idempotent: the same body twice yields the same resource.

    Args:
        project_id (UUID):
        body (ProjectReplace): Body of ``PUT /projects/{id}``. Every writable field, always.

            ``owner_id`` and ``created_at`` are server-owned and are not writable, so a
            PUT of the same body twice is genuinely the same result.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[ErrorEnvelope | ProjectRead]
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
    body: ProjectReplace,

) -> ErrorEnvelope | ProjectRead | None:
    """ Replace a project

     Sets every writable field. Idempotent: the same body twice yields the same resource.

    Args:
        project_id (UUID):
        body (ProjectReplace): Body of ``PUT /projects/{id}``. Every writable field, always.

            ``owner_id`` and ``created_at`` are server-owned and are not writable, so a
            PUT of the same body twice is genuinely the same result.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        ErrorEnvelope | ProjectRead
     """


    return (await asyncio_detailed(
        project_id=project_id,
client=client,
body=body,

    )).parsed
