"""Propose-only deploy advisor endpoints."""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session

from rudder_cp.db import get_session
from rudder_cp.routers.auth import CurrentUser
from rudder_cp.schemas.service import ServiceCreate, ServiceRead
from rudder_cp.services import services as service_ops
from rudder_cp.services.advisor import diagnose_failure, openai_completion, scan_repository
from rudder_cp.services.imports import provision_database_template
from rudder_cp.services.variables import set_variable

router = APIRouter(tags=["advisor"])
SessionDep = Annotated[Session, Depends(get_session)]


class ScanRequest(BaseModel):
    repository_path: str = Field(min_length=1, max_length=512)


class ProposalItem(BaseModel):
    kind: Literal["service", "addon", "variable"]
    payload: dict[str, Any]


class AcceptRequest(BaseModel):
    item: ProposalItem
    service_id: UUID | None = None


class DiagnosisRequest(BaseModel):
    logs: list[str] = Field(default_factory=list, max_length=100)
    service_config: dict[str, Any] = Field(default_factory=dict)


def _checkout(root: str, relative_path: str) -> Path:
    if not root:
        raise HTTPException(503, "Advisor scanning is disabled: no checkout root configured")
    base = Path(root).resolve()
    candidate = (base / relative_path).resolve()
    if base != candidate and base not in candidate.parents:
        raise HTTPException(422, "Repository path must stay within the configured checkout root")
    if not candidate.is_dir():
        raise HTTPException(404, "Repository checkout was not found")
    return candidate


@router.post("/environments/{environment_id}/advisor/scan")
async def scan(
    environment_id: UUID,
    body: ScanRequest,
    request: Request,
    session: SessionDep,
    user: CurrentUser,
):
    await service_ops.list_services(session, environment_id, owner_id=user.id)
    checkout = _checkout(request.app.state.settings.advisor_repository_root, body.repository_path)
    return scan_repository(checkout)


@router.post("/environments/{environment_id}/advisor/accept", response_model=ServiceRead | dict)
async def accept(environment_id: UUID, body: AcceptRequest, session: SessionDep, user: CurrentUser):
    """Apply one explicit click through ordinary resource service functions."""
    payload = body.item.payload
    if body.item.kind == "service":
        return ServiceRead.model_validate(await service_ops.create_service(
            session, environment_id, ServiceCreate.model_validate(payload), owner_id=user.id
        ))
    if body.item.kind == "addon":
        await service_ops.list_services(session, environment_id, owner_id=user.id)
        template = payload.get("template")
        if template not in {"postgres", "redis", "mysql"}:
            raise HTTPException(422, "Unknown advisor add-on template")
        service = provision_database_template(session, environment_id, template)
        return ServiceRead.model_validate(service)
    if body.service_id is None:
        raise HTTPException(422, "A variable proposal requires its accepted target service")
    await service_ops.get_service(session, body.service_id, owner_id=user.id)
    key, value = payload.get("key"), payload.get("value")
    if not isinstance(key, str) or not isinstance(value, str):
        raise HTTPException(422, "Invalid variable proposal")
    variable = await set_variable(session, body.service_id, key, value)
    return {"id": str(variable.id), "service_id": str(variable.service_id), "key": variable.key}


@router.post("/advisor/diagnosis")
async def diagnosis(body: DiagnosisRequest, request: Request, user: CurrentUser):
    """Return explicitly-labelled model wording; raw build logs stay in the UI."""
    _ = user
    text = await diagnose_failure(
        api_key=request.app.state.settings.openai_api_key,
        logs=body.logs,
        service_config=body.service_config,
        complete=lambda prompt: openai_completion(
            request.app.state.settings.openai_api_key, prompt
        ),
    )
    return {"enabled": text is not None, "model_generated": True, "diagnosis": text}
