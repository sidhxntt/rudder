"""API endpoints for node management.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlmodel import Session

from rudder_cp.config import get_settings
from rudder_cp.db import get_session
from rudder_cp.routers.auth import CurrentUser
from rudder_cp.schemas.nodes import (
    HeartbeatRequest,
    InstanceRead,
    NodeRead,
    NodeReadWithInstances,
    NodeRegistrationRequest,
)
from rudder_cp.services import nodes as node_service

router = APIRouter(prefix="/nodes", tags=["nodes"])
SessionDep = Annotated[Session, Depends(get_session)]


async def verify_agent_secret(x_rudder_agent_secret: str = Header(...)) -> None:
    """Dependency to verify the agent's shared secret."""
    settings = get_settings()
    if x_rudder_agent_secret != settings.agent_shared_secret:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid agent secret",
        )


@router.post("/register", status_code=status.HTTP_204_NO_CONTENT)
async def register_node(
    request: NodeRegistrationRequest,
    db: SessionDep,
    _token: None = Depends(verify_agent_secret),
) -> None:
    """Endpoint for node agents to register themselves with the control plane."""
    node_service.register_node(
        db,
        request.hostname,
        ip_address=request.ip_address,
        cpu_total=request.cpu_total,
        memory_total_mb=request.memory_total_mb,
    )


@router.post("/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
async def process_heartbeat(
    request: HeartbeatRequest,
    db: SessionDep,
    _token: None = Depends(verify_agent_secret),
) -> None:
    """Endpoint for node agents to send heartbeats."""
    node_service.process_heartbeat(db, request.hostname, request.containers)


@router.get("", response_model=list[NodeReadWithInstances])
async def list_nodes(
    db: SessionDep,
    _: CurrentUser,
) -> list[NodeReadWithInstances]:
    """List all nodes with their instances."""
    return [
        NodeReadWithInstances(
            # Validate through the base model so the response-only ``instances``
            # field is supplied exactly once below.
            **NodeRead.model_validate(node, from_attributes=True).model_dump(),
            instances=[
                InstanceRead.model_validate(instance, from_attributes=True)
                for instance in instances
            ],
        )
        for node, instances in node_service.get_all_nodes_with_instances(db)
    ]
