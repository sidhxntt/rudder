"""Service endpoints.

Created and listed under their environment, addressed by id at the top level.
Deploying a service is a different workstream and does not live here.
"""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlmodel import Session, select

from rudder_cp.db import get_session
from rudder_cp.logs.runtime import RuntimeLogNotFound, RuntimeLogStore, get_runtime_log_store
from rudder_cp.logs.sse import SSE_HEADERS, SSE_MEDIA_TYPE, frame
from rudder_cp.logs.store import LogEvent
from rudder_cp.models import Deployment, Instance, RuntimeMetric
from rudder_cp.routers.auth import CurrentUser
from rudder_cp.schemas.common import error_responses, translate_errors
from rudder_cp.schemas.domain import DomainRead
from rudder_cp.schemas.service import (
    RuntimeMetricRead,
    ServiceCreate,
    ServiceRead,
    ServiceReplace,
    ServiceUpdate,
)
from rudder_cp.services import domains as domain_ops
from rudder_cp.services import services as service_ops
from rudder_cp.services.imports import provision_database_template as provision_catalog_database

router = APIRouter(tags=["services"])

SessionDep = Annotated[Session, Depends(get_session)]
RuntimeLogStoreDep = Annotated[RuntimeLogStore, Depends(get_runtime_log_store)]


@router.post(
    "/environments/{environment_id}/database-templates/{template}",
    status_code=status.HTTP_201_CREATED,
    response_model=ServiceRead,
    responses=error_responses(404, 409, 422),
    operation_id="provision_database_template",
    summary="Provision a reviewed Postgres, Redis, or MySQL service",
)
async def provision_database_template(
    environment_id: UUID,
    template: Literal["postgres", "redis", "mysql"],
    session: SessionDep,
    user: CurrentUser,
) -> ServiceRead:
    with translate_errors():
        # Ownership check belongs to the environment boundary, not the catalog.
        await service_ops.list_services(session, environment_id, owner_id=user.id)
        service = provision_catalog_database(session, environment_id, template)
    return ServiceRead.model_validate(service)


@router.post(
    "/environments/{environment_id}/services",
    status_code=status.HTTP_201_CREATED,
    response_model=ServiceRead,
    responses=error_responses(404, 409, 422),
    operation_id="create_service",
    summary="Create a service in an environment",
    description=(
        "Also creates the service's system domain at "
        "`{name}.{environment}.{base_domain}` (D15). If that hostname is "
        "already taken the whole create fails with 409."
    ),
)
async def create_service(
    environment_id: UUID, payload: ServiceCreate, session: SessionDep, user: CurrentUser
) -> ServiceRead:
    with translate_errors():
        service = await service_ops.create_service(
            session, environment_id, payload, owner_id=user.id
        )
    return ServiceRead.model_validate(service)


@router.get(
    "/environments/{environment_id}/services",
    response_model=list[ServiceRead],
    responses=error_responses(404, 422),
    operation_id="list_services",
    summary="List an environment's services",
)
async def list_services(
    environment_id: UUID, session: SessionDep, user: CurrentUser
) -> list[ServiceRead]:
    with translate_errors():
        rows = await service_ops.list_services(session, environment_id, owner_id=user.id)
    return [ServiceRead.model_validate(row) for row in rows]


@router.get(
    "/services/{service_id}",
    response_model=ServiceRead,
    responses=error_responses(404, 422),
    operation_id="get_service",
    summary="Get a service",
)
async def get_service(service_id: UUID, session: SessionDep, user: CurrentUser) -> ServiceRead:
    with translate_errors():
        service = await service_ops.get_service(session, service_id, owner_id=user.id)
    return ServiceRead.model_validate(service)


@router.get(
    "/services/{service_id}/runtime-log",
    response_class=StreamingResponse,
    responses={
        200: {"content": {"application/json": {}, SSE_MEDIA_TYPE: {}}},
        **error_responses(404, 422),
    },
    operation_id="stream_runtime_log",
    summary="Tail a service's collected runtime log over SSE",
)
async def stream_runtime_log(
    service_id: UUID, session: SessionDep, user: CurrentUser, store: RuntimeLogStoreDep,
    follow: bool = True,
) -> StreamingResponse:
    with translate_errors():
        await service_ops.get_service(session, service_id, owner_id=user.id)
    if not store.exists(service_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No runtime log collected yet"
        )

    async def events():
        try:
            if not follow:
                text = await store.snapshot(service_id)
                if text:
                    yield frame(LogEvent("chunk", text))
                yield frame(LogEvent("end", "snapshot"))
                return
            async for event in store.tail(service_id):
                yield frame(event)
        except RuntimeLogNotFound:
            return

    return StreamingResponse(events(), media_type=SSE_MEDIA_TYPE, headers=SSE_HEADERS)


@router.get(
    "/services/{service_id}/metrics",
    response_model=list[RuntimeMetricRead],
    responses=error_responses(404, 422),
    operation_id="list_service_metrics",
    summary="Read retained CPU and memory samples for a service",
)
async def list_service_metrics(
    service_id: UUID,
    session: SessionDep,
    user: CurrentUser,
    window: Literal["1h", "24h", "7d"] = "1h",
) -> list[RuntimeMetricRead]:
    with translate_errors():
        await service_ops.get_service(session, service_id, owner_id=user.id)
    seconds, resolution = {"1h": (3600, 10), "24h": (86400, 60), "7d": (604800, 300)}[window]
    after = datetime.now(UTC) - timedelta(seconds=seconds)
    rows = session.exec(
        select(RuntimeMetric)
        .join(Instance, Instance.id == RuntimeMetric.instance_id)  # type: ignore[arg-type]
        .join(Deployment, Deployment.id == Instance.deployment_id)  # type: ignore[arg-type]
        .where(
            Deployment.service_id == service_id,
            RuntimeMetric.resolution_seconds == resolution,
            RuntimeMetric.captured_at >= after,
        )
        .order_by(RuntimeMetric.captured_at)
    ).all()
    return [RuntimeMetricRead.model_validate(row) for row in rows]


@router.patch(
    "/services/{service_id}",
    response_model=ServiceRead,
    responses=error_responses(404, 409, 422),
    operation_id="update_service",
    summary="Partially update a service",
    description=(
        "Fields left out are untouched. Renaming rewrites the system domain "
        "hostname. `canvas_x` / `canvas_y` are UI metadata (D6): they persist "
        "and trigger nothing."
    ),
)
async def update_service(
    service_id: UUID, payload: ServiceUpdate, session: SessionDep, user: CurrentUser
) -> ServiceRead:
    with translate_errors():
        service = await service_ops.update_service(session, service_id, payload, owner_id=user.id)
    return ServiceRead.model_validate(service)


@router.put(
    "/services/{service_id}",
    response_model=ServiceRead,
    responses=error_responses(404, 409, 422),
    operation_id="replace_service",
    summary="Replace a service",
    description=(
        "Sets every writable field, resetting anything omitted to its default. "
        "Idempotent: the same body twice yields the same resource."
    ),
)
async def replace_service(
    service_id: UUID, payload: ServiceReplace, session: SessionDep, user: CurrentUser
) -> ServiceRead:
    with translate_errors():
        service = await service_ops.replace_service(session, service_id, payload, owner_id=user.id)
    return ServiceRead.model_validate(service)


@router.delete(
    "/services/{service_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    responses=error_responses(404, 422, 503),
    operation_id="delete_service",
    summary="Delete a service and everything in it",
    description=(
        "Cascades to its system domain, any domain targeting it or one of its "
        "deployments, its variables, volumes, deployments and instances. A "
        "volume-backed service requires confirm_volume_deletion=true; this "
        "removes Rudder's record but intentionally leaves the Docker volume."
    ),
)
async def delete_service(
    service_id: UUID,
    request: Request,
    session: SessionDep,
    user: CurrentUser,
    confirm_volume_deletion: bool = False,
) -> None:
    with translate_errors():
        settings = request.app.state.settings
        await service_ops.delete_service(
            session,
            service_id,
            agent=request.app.state.agent,
            settings=settings,
            confirm_volume_deletion=confirm_volume_deletion,
            owner_id=user.id,
        )


@router.get(
    "/services/{service_id}/domains",
    response_model=list[DomainRead],
    responses=error_responses(404, 422),
    operation_id="list_service_domains",
    summary="List every hostname that resolves to a service",
)
async def list_service_domains(
    service_id: UUID, session: SessionDep, user: CurrentUser
) -> list[DomainRead]:
    with translate_errors():
        await service_ops.get_service(session, service_id, owner_id=user.id)
        rows = await domain_ops.list_domains_for_service(session, service_id)
    return [DomainRead.model_validate(row) for row in rows]
