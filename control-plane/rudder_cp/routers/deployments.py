"""Deployment endpoints.

`POST /services/{id}/deploy` does not deploy. It writes Deployment(queued) and
returns 202. The background worker does the work. Long work never runs inside a
request — a build takes minutes and an HTTP client will not wait.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from rudder_cp.config import Settings, get_settings
from rudder_cp.db import get_session
from rudder_cp.models import Deployment, DeploymentStatus, Instance, InstanceStatus, Service
from rudder_cp.services.rollbacks import restore_immutable_deployment

router = APIRouter(tags=["deployments"])

SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


class DeploymentRead(BaseModel):
    id: uuid.UUID
    service_id: uuid.UUID
    status: DeploymentStatus
    image_tag: str | None
    commit_sha: str | None
    error_message: str | None
    created_at: datetime
    became_live_at: datetime | None

    model_config = {"from_attributes": True}


class DeployRequest(BaseModel):
    """An explicit SHA is optional. Without one the build resolves the branch tip."""

    # Keep invalid revision input out of the transactional path. The immutable
    # artifact model deliberately stores canonical Git SHA-1 identifiers.
    commit_sha: str | None = Field(default=None, max_length=40)


class InstanceRead(BaseModel):
    id: uuid.UUID
    deployment_id: uuid.UUID
    node_id: uuid.UUID
    status: InstanceStatus
    container_id: str | None
    started_at: datetime | None
    stopped_at: datetime | None

    model_config = {"from_attributes": True}


@router.post(
    "/services/{service_id}/deploy",
    response_model=DeploymentRead,
    status_code=status.HTTP_200_OK,
    operation_id="create_deployment",
    summary="Queue a deployment",
    description=(
        "Writes Deployment(status=queued) and returns 202. The build runs in a "
        "background worker; poll the deployment or stream its build log."
    ),
)
async def create_deployment(
    service_id: uuid.UUID,
    session: SessionDep,
    body: DeployRequest | None = None,
) -> Deployment:
    service = session.get(Service, service_id)
    if service is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "No such service", "details": {}},
        )
    managed_by_service_id = service.build_config.get("managed_by_service_id")
    if isinstance(managed_by_service_id, str):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "managed_by_compose",
                "message": "This service is managed by its owning Compose release.",
                "details": {"release_service_id": managed_by_service_id},
            },
        )
    managed_image = service.build_config.get("managed_image")
    if not service.source_repo and not isinstance(managed_image, str):
        raise HTTPException(
            status_code=422,
            detail={
                "code": "no_source_repo",
                "message": "This service has no source_repo or managed image to deploy.",
                "details": {"service_id": str(service_id)},
            },
        )
    deployment = Deployment(
        service_id=service_id,
        commit_sha=(body.commit_sha if body else None),
        status=DeploymentStatus.QUEUED,
    )
    session.add(deployment)
    session.commit()
    session.refresh(deployment)
    return deployment


@router.post(
    "/deployments/{deployment_id}/rollback",
    response_model=DeploymentRead,
    status_code=status.HTTP_202_ACCEPTED,
    operation_id="rollback_deployment",
    summary="Roll back to a successful immutable release",
    description=(
        "Instantly repoints the service to a prior healthy immutable release. "
        "No build, image pull, or container restart is performed."
    ),
)
async def rollback_deployment(
    deployment_id: uuid.UUID, session: SessionDep, settings: SettingsDep
) -> Deployment:
    """Restore by moving the existing immutable traffic target only."""
    return await restore_immutable_deployment(
        session, deployment_id=deployment_id, settings=settings
    )


@router.get(
    "/services/{service_id}/deployments",
    response_model=list[DeploymentRead],
    operation_id="list_deployments",
    summary="Deploy history for a service, newest first",
)
async def list_deployments(service_id: uuid.UUID, session: SessionDep) -> list[Deployment]:
    release_service_id = _release_owner_id(session, service_id)
    return list(
        session.exec(
            select(Deployment)
            .where(Deployment.service_id == release_service_id)
            .order_by(Deployment.created_at.desc())  # type: ignore[attr-defined]
        ).all()
    )


@router.get(
    "/services/{service_id}/instances",
    response_model=list[InstanceRead],
    operation_id="list_instances",
    summary="Running containers for a service",
    description=(
        "Instance is the fact, Deployment is the intent. A service is only "
        "actually serving if it has a healthy instance, which is what makes this "
        "distinct from the deployment status."
    ),
)
async def list_instances(service_id: uuid.UUID, session: SessionDep) -> list[Instance]:
    release_service_id = _release_owner_id(session, service_id)
    return list(
        session.exec(
            select(Instance)
            .join(Deployment, Deployment.id == Instance.deployment_id)  # type: ignore[arg-type]
            .where(Deployment.service_id == release_service_id)
            .order_by(Instance.created_at.desc())  # type: ignore[attr-defined]
        ).all()
    )


def _release_owner_id(session: Session, service_id: uuid.UUID) -> uuid.UUID:
    """Return the one deployment owner for a Compose-managed child service.

    Compose releases have exactly one ``Deployment`` record: the route-owning
    application service. Child services intentionally do not create their own
    deployments, but their panels still need the same immutable history and
    build-log identifiers.
    """
    service = session.get(Service, service_id)
    if service is None:
        return service_id
    value = service.build_config.get("managed_by_service_id")
    if not isinstance(value, str):
        return service_id
    try:
        return uuid.UUID(value)
    except ValueError:
        return service_id


@router.get(
    "/deployments/{deployment_id}",
    response_model=DeploymentRead,
    operation_id="get_deployment",
    summary="One deployment",
)
async def get_deployment(deployment_id: uuid.UUID, session: SessionDep) -> Deployment:
    deployment = session.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "not_found", "message": "No such deployment", "details": {}},
        )
    return deployment
