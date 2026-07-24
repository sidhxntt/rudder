"""Setup-ready endpoints for the GitHub App repository import flow."""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from rudder_cp.services.github_app import GitHubAppError
from rudder_cp.services.imports import detect_node_addons

router = APIRouter(tags=["github-import"])


class GitHubImportStatus(BaseModel):
    configured: bool
    install_url: str | None
    message: str


class GitHubRepositoryRead(BaseModel):
    full_name: str
    default_branch: str
    private: bool


class GitHubImportPreviewRequest(BaseModel):
    installation_id: int
    repository: str
    branch: str


class GitHubImportPreview(BaseModel):
    is_node_app: bool
    addons: list[str]
    externally_managed: list[str]


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
    except GitHubAppError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    proposal = detect_node_addons(package_json, existing_variable_keys=set())
    return GitHubImportPreview(
        is_node_app=proposal.is_node_app,
        addons=list(proposal.addons),
        externally_managed=list(proposal.externally_managed),
    )
