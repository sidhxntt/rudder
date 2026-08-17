"""Protected read-only operator assistant endpoint."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlmodel import Session

from rudder_cp.db import get_session
from rudder_cp.routers.auth import CurrentUser
from rudder_cp.services.assistant import (
    build_context,
    load_knowledge_documents,
    openai_completion,
    respond,
)

router = APIRouter(tags=["assistant"])
SessionDep = Annotated[Session, Depends(get_session)]


class AssistantTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4_000)


class AssistantMessage(BaseModel):
    message: str = Field(min_length=1, max_length=4_000)
    prior_turns: list[AssistantTurn] = Field(default_factory=list, max_length=6)


@router.post("/environments/{environment_id}/assistant/messages")
async def message(
    environment_id: UUID,
    body: AssistantMessage,
    request: Request,
    session: SessionDep,
    user: CurrentUser,
):
    try:
        context = build_context(session, environment_id, owner_id=user.id)
    except LookupError as exc:
        raise HTTPException(404, "Environment not found") from exc
    complete = getattr(request.app.state, "assistant_complete", None)
    if complete is None:

        async def default_complete(prompt: str) -> str:
            return await openai_completion(
                request.app.state.settings.openai_api_key,
                prompt,
                model=request.app.state.settings.assistant_model,
            )

        complete = default_complete
    return await respond(
        api_key=request.app.state.settings.openai_api_key,
        message=body.message,
        prior_turns=[turn.model_dump() for turn in body.prior_turns],
        context=context,
        docs=load_knowledge_documents(),
        complete=complete,
        model=getattr(request.app.state.settings, "assistant_model", "gpt-4.1-mini"),
    )
