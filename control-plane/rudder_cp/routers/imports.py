"""Setup-ready endpoints for the GitHub App repository import flow."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter(tags=["github-import"])


class GitHubImportStatus(BaseModel):
    configured: bool
    install_url: str | None
    message: str


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
