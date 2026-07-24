"""Setup-ready endpoints for the GitHub App repository import flow."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlmodel import Session, select

from rudder_cp.db import get_session
from rudder_cp.models import Environment, GitHubImport
from rudder_cp.services.compose import (
    ComposeValidationError,
    GeneratedProcess,
    resolve_compose_plan,
    starter_template,
    starter_templates,
)
from rudder_cp.services.github_app import GitHubAppError
from rudder_cp.services.imports import (
    detect_node_addons,
    import_progress,
    provision_import,
)
from rudder_cp.services.processes import detect_processes

router = APIRouter(tags=["github-import"])
SessionDep = Annotated[Session, Depends(get_session)]


class GitHubImportStatus(BaseModel):
    configured: bool
    install_url: str | None
    message: str


class StarterTemplateRead(BaseModel):
    id: str
    name: str
    description: str
    addons: list[str]


class GitHubRepositoryRead(BaseModel):
    full_name: str
    default_branch: str
    private: bool


class GitHubInstallationRead(BaseModel):
    id: int
    account_login: str
    repository_selection: str


class GitHubImportPreviewRequest(BaseModel):
    installation_id: int
    repository: str
    branch: str
    template_id: str | None = None


class GitHubImportPreview(BaseModel):
    is_node_app: bool
    addons: list[str]
    externally_managed: list[str]
    compose_source: str
    compose_manifest: str
    services: list["ComposeServicePreview"]
    processes: list["ProcessPreview"]


class ComposeServicePreview(BaseModel):
    name: str
    public_port: int | None
    container_port: int | None
    role: str
    is_public: bool


class ProcessPreview(BaseModel):
    role: str
    command: str
    source: str


class GitHubImportConfirmRequest(GitHubImportPreviewRequest):
    addons: list[str]
    public_services: list[str] | None = None


class GitHubImportConfirm(BaseModel):
    import_id: uuid.UUID
    project_id: uuid.UUID
    environment_id: uuid.UUID
    app_service_id: uuid.UUID


class GitHubImportStep(BaseModel):
    label: str
    service_id: uuid.UUID
    service_name: str | None
    deployment_id: uuid.UUID | None
    status: str
    error_message: str | None


class GitHubImportRead(GitHubImportConfirm):
    repository: str
    branch: str
    steps: list[GitHubImportStep]


@router.get("/github/import/status", response_model=GitHubImportStatus)
async def github_import_status(request: Request) -> GitHubImportStatus:
    settings = request.app.state.settings
    if not settings.github_app_configured:
        return GitHubImportStatus(
            configured=False,
            install_url=None,
            message="GitHub App credentials are not configured.",
        )
    return GitHubImportStatus(
        configured=True,
        install_url=f"https://github.com/apps/{settings.github_app_slug}/installations/new",
        message="Connect GitHub to choose a repository.",
    )


@router.get("/github/import/templates", response_model=list[StarterTemplateRead])
async def github_import_templates() -> list[StarterTemplateRead]:
    return [
        StarterTemplateRead(
            id=template.id,
            name=template.name,
            description=template.description,
            addons=list(template.addons),
        )
        for template in starter_templates()
    ]


@router.get("/github/import/repositories", response_model=list[GitHubRepositoryRead])
async def github_repositories(installation_id: int, request: Request) -> list[GitHubRepositoryRead]:
    try:
        rows = await request.app.state.github.repositories(installation_id)
    except GitHubAppError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return [
        GitHubRepositoryRead(
            full_name=row.full_name,
            default_branch=row.default_branch,
            private=row.private,
        )
        for row in rows
    ]


@router.get("/github/import/installations", response_model=list[GitHubInstallationRead])
async def github_installations(request: Request) -> list[GitHubInstallationRead]:
    try:
        rows = await request.app.state.github.installations()
    except GitHubAppError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return [
        GitHubInstallationRead(
            id=row.id,
            account_login=row.account_login,
            repository_selection=row.repository_selection,
        )
        for row in rows
    ]


@router.get("/github/import/branches", response_model=list[str])
async def github_branches(installation_id: int, repository: str, request: Request) -> list[str]:
    try:
        return await request.app.state.github.branches(installation_id, repository)
    except GitHubAppError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/github/import/preview", response_model=GitHubImportPreview)
async def github_import_preview(
    payload: GitHubImportPreviewRequest, request: Request
) -> GitHubImportPreview:
    try:
        package_json = await request.app.state.github.package_json(
            payload.installation_id, payload.repository, payload.branch
        )
        procfile = await request.app.state.github.file_at_ref(
            payload.installation_id, payload.repository, payload.branch, "Procfile"
        )
    except GitHubAppError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    proposal = detect_node_addons(package_json, existing_variable_keys=set())
    template = starter_template(payload.template_id)
    if payload.template_id is not None and template is None:
        raise HTTPException(status_code=422, detail="Unknown starter template.")
    reviewed_addons = set(proposal.addons) | set(template.addons if template else ())
    processes = tuple(
        GeneratedProcess(role=process.role, command=process.command)
        for process in detect_processes(package_json, procfile)
    )
    compose_plan = await resolve_compose_plan(
        request.app.state.github,
        installation_id=payload.installation_id,
        repository=payload.repository,
        branch=payload.branch,
        selected_addons=reviewed_addons,
        generated_processes=processes,
    )
    return GitHubImportPreview(
        is_node_app=proposal.is_node_app,
        addons=sorted(reviewed_addons),
        externally_managed=list(proposal.externally_managed),
        compose_source=compose_plan.source,
        compose_manifest=compose_plan.yaml,
        services=[
            ComposeServicePreview(
                name=service.name,
                public_port=service.public_port,
                container_port=service.container_port,
                role=service.role,
                is_public=service.is_public,
            )
            for service in compose_plan.services.values()
        ],
        processes=[
            ProcessPreview(role=process.role, command=process.command, source=process.source)
            for process in detect_processes(package_json, procfile)
        ],
    )


@router.post(
    "/github/imports",
    response_model=GitHubImportConfirm,
    status_code=status.HTTP_201_CREATED,
)
async def confirm_github_import(
    payload: GitHubImportConfirmRequest,
    request: Request,
    session: SessionDep,
) -> GitHubImportConfirm:
    """Confirm the review screen, create the app graph, and queue its deploys."""
    try:
        package_json = await request.app.state.github.package_json(
            payload.installation_id, payload.repository, payload.branch
        )
        procfile = await request.app.state.github.file_at_ref(
            payload.installation_id, payload.repository, payload.branch, "Procfile"
        )
        proposal = detect_node_addons(package_json, existing_variable_keys=set())
        template = starter_template(payload.template_id)
        if payload.template_id is not None and template is None:
            raise ValueError("Unknown starter template.")
        proposal = type(proposal)(
            is_node_app=proposal.is_node_app,
            addons=tuple(sorted(set(proposal.addons) | set(template.addons if template else ()))),
            externally_managed=proposal.externally_managed,
        )
        compose_plan = await resolve_compose_plan(
            request.app.state.github,
            installation_id=payload.installation_id,
            repository=payload.repository,
            branch=payload.branch,
            selected_addons=set(payload.addons),
            generated_processes=tuple(
                GeneratedProcess(role=process.role, command=process.command)
                for process in detect_processes(package_json, procfile)
            ),
        )
        created = await provision_import(
            session,
            installation_id=payload.installation_id,
            repository=payload.repository,
            branch=payload.branch,
            selected_addons=set(payload.addons),
            proposal=proposal,
            selected_public_services=(
                set(payload.public_services) if payload.public_services is not None else None
            ),
            compose_plan=compose_plan,
        )
    except GitHubAppError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (ComposeValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return GitHubImportConfirm(
        import_id=created.import_id,
        project_id=created.project_id,
        environment_id=created.environment_id,
        app_service_id=created.app_service_id,
    )


@router.get("/github/imports/{import_id}", response_model=GitHubImportRead)
async def get_github_import(
    import_id: uuid.UUID, session: SessionDep
) -> GitHubImportRead:
    record = session.get(GitHubImport, import_id)
    if record is None:
        raise HTTPException(status_code=404, detail="GitHub import not found.")
    return GitHubImportRead(
        import_id=record.id,
        project_id=record.project_id,
        environment_id=_environment_id(session, record.project_id),
        app_service_id=record.app_service_id,
        repository=record.repository,
        branch=record.branch,
        steps=[GitHubImportStep(**step) for step in import_progress(session, record)],
    )


def _environment_id(session: Session, project_id: uuid.UUID) -> uuid.UUID:
    environment = session.exec(
        select(Environment).where(
            Environment.project_id == project_id,
            Environment.is_production.is_(True),
        )
    ).one()
    return environment.id
