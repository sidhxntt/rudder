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
    deployment_id: UUID,

) -> dict[str, Any]:






    _kwargs: dict[str, Any] = {
        "method": "get",
        "url": "/deployments/{deployment_id}/build-log".format(deployment_id=quote(str(deployment_id), safe=""),),
    }


    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Any | HTTPValidationError | None:
    if response.status_code == 200:
        response_200 = cast(Any, None)
        return response_200

    if response.status_code == 404:
        response_404 = cast(Any, None)
        return response_404

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
    deployment_id: UUID,
    *,
    client: AuthenticatedClient | Client,

) -> Response[Any | HTTPValidationError]:
    """ Stream a deployment's build log (SSE)

     Tail the build log from the beginning and follow it until the build ends.

    Returns the full log and a clean ``event: end`` for a build that already
    finished, keeps streaming for one still running, and 404s when no log
    exists rather than hanging on a stream that will never produce anything.

    Args:
        deployment_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
     """


    kwargs = _get_kwargs(
        deployment_id=deployment_id,

    )

    response = client.get_httpx_client().request(
        **kwargs,
    )

    return _build_response(client=client, response=response)

def sync(
    deployment_id: UUID,
    *,
    client: AuthenticatedClient | Client,

) -> Any | HTTPValidationError | None:
    """ Stream a deployment's build log (SSE)

     Tail the build log from the beginning and follow it until the build ends.

    Returns the full log and a clean ``event: end`` for a build that already
    finished, keeps streaming for one still running, and 404s when no log
    exists rather than hanging on a stream that will never produce anything.

    Args:
        deployment_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
     """


    return sync_detailed(
        deployment_id=deployment_id,
client=client,

    ).parsed

async def asyncio_detailed(
    deployment_id: UUID,
    *,
    client: AuthenticatedClient | Client,

) -> Response[Any | HTTPValidationError]:
    """ Stream a deployment's build log (SSE)

     Tail the build log from the beginning and follow it until the build ends.

    Returns the full log and a clean ``event: end`` for a build that already
    finished, keeps streaming for one still running, and 404s when no log
    exists rather than hanging on a stream that will never produce anything.

    Args:
        deployment_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[Any | HTTPValidationError]
     """


    kwargs = _get_kwargs(
        deployment_id=deployment_id,

    )

    response = await client.get_async_httpx_client().request(
        **kwargs
    )

    return _build_response(client=client, response=response)

async def asyncio(
    deployment_id: UUID,
    *,
    client: AuthenticatedClient | Client,

) -> Any | HTTPValidationError | None:
    """ Stream a deployment's build log (SSE)

     Tail the build log from the beginning and follow it until the build ends.

    Returns the full log and a clean ``event: end`` for a build that already
    finished, keeps streaming for one still running, and 404s when no log
    exists rather than hanging on a stream that will never produce anything.

    Args:
        deployment_id (UUID):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Any | HTTPValidationError
     """


    return (await asyncio_detailed(
        deployment_id=deployment_id,
client=client,

    )).parsed
