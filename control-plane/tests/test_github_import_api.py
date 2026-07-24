from fastapi import FastAPI
from fastapi.testclient import TestClient

from rudder_cp.config import get_settings
from rudder_cp.routers import imports as imports_router


def test_github_import_status_reports_setup_required_when_app_is_unconfigured(
    monkeypatch,
) -> None:
    monkeypatch.delenv("RUDDER_GITHUB_APP_ID", raising=False)
    monkeypatch.delenv("RUDDER_GITHUB_APP_PRIVATE_KEY", raising=False)
    get_settings.cache_clear()
    try:
        app = FastAPI()
        app.state.settings = get_settings()
        app.include_router(imports_router.router)
        response = TestClient(app).get("/github/import/status")
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    assert response.json() == {
        "configured": False,
        "install_url": None,
        "message": "GitHub App credentials are not configured.",
    }
