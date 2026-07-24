"""Deployment endpoints.

`POST /services/{id}/deploy` does not deploy. It writes Deployment(queued) and
returns 202. The background worker does the work. Long work never runs inside a
request — a build takes minutes and an HTTP client will not wait.
"""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from rudder_cp.db import get_session
from rudder_cp.models import Deployment, DeploymentStatus, Instance, InstanceStatus, Service

router = APIRouter(tags=["deployments"])

SessionDep = Annotated[Session, Depends(get_session)]


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

    commit_sha: str | None = None


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
    status_code=status.HTTP_202_ACCEPTED,
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
    if not service.source_repo:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "no_source_repo",
                "message": "This service has no source_repo, so there is nothing to build.",
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


@router.get(
    "/services/{service_id}/deployments",
    response_model=list[DeploymentRead],
    operation_id="list_deployments",
    summary="Deploy history for a service, newest first",
)
async def list_deployments(service_id: uuid.UUID, session: SessionDep) -> list[Deployment]:
    return list(
        session.exec(
            select(Deployment)
            .where(Deployment.service_id == service_id)
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
    return list(
        session.exec(
            select(Instance)
            .join(Deployment, Deployment.id == Instance.deployment_id)  # type: ignore[arg-type]
            .where(Deployment.service_id == service_id)
            .order_by(Instance.created_at.desc())  # type: ignore[attr-defined]
        ).all()
    )


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
