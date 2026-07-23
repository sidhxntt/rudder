from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.deploy_request import DeployRequest
from ...models.deployment_read import DeploymentRead
from ...models.http_validation_error import HTTPValidationError
from ...types import UNSET, Unset
from typing import cast
from uuid import UUID



def _get_kwargs(
    service_id: UUID,
    *,
    body: DeployRequest | None | Unset = UNSET,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}






    _kwargs: dict[str, Any] = {
        "method": "post",
        "url": "/services/{service_id}/deploy".format(service_id=quote(str(service_id), safe=""),),
    }


    if isinstance(body, DeployRequest):
        _kwargs["json"] = body.to_dict()
    else:
        _kwargs["json"] = body

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> DeploymentRead | HTTPValidationError | None:
    if response.status_code == 202:
        response_202 = DeploymentRead.from_dict(response.json())



        return response_202

    if response.status_code == 422:
        response_422 = HTTPValidationError.from_dict(response.json())



        return response_422

    if client.raise_on_unexpected_status:
        raise errors.UnexpectedStatus(response.status_code, response.content)
    else:
        return None


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[DeploymentRead | HTTPValidationError]:
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
    body: DeployRequest | None | Unset = UNSET,

) -> Response[DeploymentRead | HTTPValidationError]:
    """ Queue a deployment

     Writes Deployment(status=queued) and returns 202. The build runs in a background worker; poll the
    deployment or stream its build log.

    Args:
        service_id (UUID):
        body (DeployRequest | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DeploymentRead | HTTPValidationError]
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
    body: DeployRequest | None | Unset = UNSET,

) -> DeploymentRead | HTTPValidationError | None:
    """ Queue a deployment

     Writes Deployment(status=queued) and returns 202. The build runs in a background worker; poll the
    deployment or stream its build log.

    Args:
        service_id (UUID):
        body (DeployRequest | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DeploymentRead | HTTPValidationError
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
    body: DeployRequest | None | Unset = UNSET,

) -> Response[DeploymentRead | HTTPValidationError]:
    """ Queue a deployment

     Writes Deployment(status=queued) and returns 202. The build runs in a background worker; poll the
    deployment or stream its build log.

    Args:
        service_id (UUID):
        body (DeployRequest | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[DeploymentRead | HTTPValidationError]
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
    body: DeployRequest | None | Unset = UNSET,

) -> DeploymentRead | HTTPValidationError | None:
    """ Queue a deployment

     Writes Deployment(status=queued) and returns 202. The build runs in a background worker; poll the
    deployment or stream its build log.

    Args:
        service_id (UUID):
        body (DeployRequest | None | Unset):

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        DeploymentRead | HTTPValidationError
     """


    return (await asyncio_detailed(
        service_id=service_id,
client=client,
body=body,

    )).parsed
