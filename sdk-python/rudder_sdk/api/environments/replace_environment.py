from http import HTTPStatus
from typing import Any, cast
from urllib.parse import quote

import httpx

from ...client import AuthenticatedClient, Client
from ...types import Response, UNSET
from ... import errors

from ...models.environment_read import EnvironmentRead
from ...models.environment_replace import EnvironmentReplace
from ...models.error_envelope import ErrorEnvelope
from typing import cast
from uuid import UUID



def _get_kwargs(
    environment_id: UUID,
    *,
    body: EnvironmentReplace,

) -> dict[str, Any]:
    headers: dict[str, Any] = {}






    _kwargs: dict[str, Any] = {
        "method": "put",
        "url": "/environments/{environment_id}".format(environment_id=quote(str(environment_id), safe=""),),
    }

    _kwargs["json"] = body.to_dict()

    headers["Content-Type"] = "application/json"

    _kwargs["headers"] = headers
    return _kwargs



def _parse_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> EnvironmentRead | ErrorEnvelope | None:
    if response.status_code == 200:
        response_200 = EnvironmentRead.from_dict(response.json())



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


def _build_response(*, client: AuthenticatedClient | Client, response: httpx.Response) -> Response[EnvironmentRead | ErrorEnvelope]:
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
    body: EnvironmentReplace,

) -> Response[EnvironmentRead | ErrorEnvelope]:
    """ Replace an environment

     Sets every writable field. `wg_subnet` is server-owned and is not replaceable. Idempotent.

    Args:
        environment_id (UUID):
        body (EnvironmentReplace): Body of ``PUT /environments/{id}``.

            ``wg_subnet`` is intentionally absent. It is allocated once at create time
            and never renumbered, so it cannot participate in a full replacement
            without breaking the mesh in Phase 3.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvironmentRead | ErrorEnvelope]
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
    body: EnvironmentReplace,

) -> EnvironmentRead | ErrorEnvelope | None:
    """ Replace an environment

     Sets every writable field. `wg_subnet` is server-owned and is not replaceable. Idempotent.

    Args:
        environment_id (UUID):
        body (EnvironmentReplace): Body of ``PUT /environments/{id}``.

            ``wg_subnet`` is intentionally absent. It is allocated once at create time
            and never renumbered, so it cannot participate in a full replacement
            without breaking the mesh in Phase 3.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvironmentRead | ErrorEnvelope
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
    body: EnvironmentReplace,

) -> Response[EnvironmentRead | ErrorEnvelope]:
    """ Replace an environment

     Sets every writable field. `wg_subnet` is server-owned and is not replaceable. Idempotent.

    Args:
        environment_id (UUID):
        body (EnvironmentReplace): Body of ``PUT /environments/{id}``.

            ``wg_subnet`` is intentionally absent. It is allocated once at create time
            and never renumbered, so it cannot participate in a full replacement
            without breaking the mesh in Phase 3.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        Response[EnvironmentRead | ErrorEnvelope]
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
    body: EnvironmentReplace,

) -> EnvironmentRead | ErrorEnvelope | None:
    """ Replace an environment

     Sets every writable field. `wg_subnet` is server-owned and is not replaceable. Idempotent.

    Args:
        environment_id (UUID):
        body (EnvironmentReplace): Body of ``PUT /environments/{id}``.

            ``wg_subnet`` is intentionally absent. It is allocated once at create time
            and never renumbered, so it cannot participate in a full replacement
            without breaking the mesh in Phase 3.

    Raises:
        errors.UnexpectedStatus: If the server returns an undocumented status code and Client.raise_on_unexpected_status is True.
        httpx.TimeoutException: If the request takes longer than Client.timeout.

    Returns:
        EnvironmentRead | ErrorEnvelope
     """


    return (await asyncio_detailed(
        environment_id=environment_id,
client=client,
body=body,

    )).parsed
