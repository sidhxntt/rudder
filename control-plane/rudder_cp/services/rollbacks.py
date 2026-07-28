"""Shared immutable deployment restore primitive.

Both the dashboard deployment endpoint and the operations worker use this
function.  Keeping it here prevents the two paths from drifting into one path
that rebuilds source and another that changes traffic safely.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlmodel import Session, select

from rudder_cp.config import Settings
from rudder_cp.models import Deployment, DeploymentStatus, Instance, InstanceStatus
from rudder_cp.services import traefik


async def restore_immutable_deployment(
    session: Session, *, deployment_id: UUID, settings: Settings
) -> Deployment:
    """Promote an existing healthy immutable release; never build or restart it."""
    source = session.get(Deployment, deployment_id)
    if source is None:
        raise HTTPException(status_code=404, detail="No such deployment")
    if source.status not in {DeploymentStatus.LIVE, DeploymentStatus.SUPERSEDED}:
        raise HTTPException(status_code=422, detail="Only successful deployments can be restored")
    healthy_target = session.exec(
        select(Instance).where(
            Instance.deployment_id == source.id,
            Instance.status == InstanceStatus.HEALTHY,
        )
    ).first()
    if healthy_target is None:
        raise HTTPException(status_code=422, detail="Immutable restore target is not healthy")
    current = session.exec(
        select(Deployment).where(
            Deployment.service_id == source.service_id,
            Deployment.status == DeploymentStatus.LIVE,
            Deployment.id != source.id,
        )
    ).all()
    for deployment in current:
        deployment.status = DeploymentStatus.SUPERSEDED
        session.add(deployment)
    source.status = DeploymentStatus.LIVE
    source.error_message = None
    source.became_live_at = datetime.now(UTC)
    session.add(source)
    session.commit()
    # This is the public-route promotion checkpoint. The target was verified
    # healthy before we moved the live pointer; rendering cannot build or pull.
    await traefik.render_all(session, settings)
    session.refresh(source)
    return source
