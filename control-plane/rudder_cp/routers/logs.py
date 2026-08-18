"""Build log streaming.

D4: Phase 1 exposes build logs only; container runtime logs are Phase 5.

Resource-oriented per the PRD's API rules -- the Deployment is the resource and
the build log is a sub-resource of it, so this is a GET on
``/deployments/{deployment_id}/build-log``, not an RPC verb.

No auth dependency here on purpose: auth is a separate workstream and wires in
at mount time.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlmodel import Session

from rudder_cp.db import get_session
from rudder_cp.logs.sse import SSE_HEADERS, SSE_MEDIA_TYPE, build_log_events
from rudder_cp.logs.store import BuildLogStore, get_build_log_store
from rudder_cp.models import Deployment
from rudder_cp.routers.auth import CurrentUser
from rudder_cp.services import services as service_ops

router = APIRouter(prefix="/deployments", tags=["deployments"])

StoreDep = Annotated[BuildLogStore, Depends(get_build_log_store)]
SessionDep = Annotated[Session, Depends(get_session)]


@router.get(
    "/{deployment_id}/build-log",
    summary="Stream a deployment's build log (SSE)",
    response_class=StreamingResponse,
    responses={
        200: {"content": {SSE_MEDIA_TYPE: {}}, "description": "Build log event stream"},
        404: {"description": "No build log for this deployment"},
    },
)
async def stream_build_log(
    deployment_id: UUID,
    store: StoreDep,
    session: SessionDep,
    user: CurrentUser,
    follow: bool = True,
) -> StreamingResponse:
    """Tail the build log from the beginning and follow it until the build ends.

    Returns the full log and a clean ``event: end`` for a build that already
    finished, keeps streaming for one still running, and 404s when no log
    exists rather than hanging on a stream that will never produce anything.
    """
    deployment = session.get(Deployment, deployment_id)
    if deployment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No build log for deployment {deployment_id}",
        )
    await service_ops.get_service(session, deployment.service_id, owner_id=user.id)
    if not store.exists(deployment_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No build log for deployment {deployment_id}",
        )
    return StreamingResponse(
        build_log_events(store, deployment_id, follow=follow),
        media_type=SSE_MEDIA_TYPE,
        headers=SSE_HEADERS,
    )
