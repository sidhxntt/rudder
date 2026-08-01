"""Private, separately-authorised GKE backup identity broker.

This app runs in its own Pod and is the sole Rudder workload permitted to add
per-environment Workload Identity members to the dedicated backup GSA.  It has
no public Service or Ingress; a NetworkPolicy admits only the control plane.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from rudder_cp.runtime.backup_identity import (
    GkeBackupIdentityBroker,
    GoogleIamPolicyApi,
    MetadataGoogleIamPolicyApi,
)


class CloudNativePgBindingRequest(BaseModel):
    namespace: str
    service_account_name: str


def create_backup_identity_broker_app(
    *,
    project_id: str | None = None,
    backup_service_account: str | None = None,
    iam_factory: Callable[[], GoogleIamPolicyApi] = MetadataGoogleIamPolicyApi,
) -> FastAPI:
    """Build the minimal internal-only broker application.

    Configuration is supplied separately from the control-plane runtime secret;
    the broker does not receive user sessions, GitHub credentials, database
    credentials, or bucket keys.
    """

    configured_project_id = project_id or os.environ.get("RUDDER_GCP_PROJECT_ID", "")
    configured_backup_gsa = backup_service_account or os.environ.get(
        "RUDDER_KUBERNETES_BACKUP_GCP_SERVICE_ACCOUNT", ""
    )
    app = FastAPI(title="Rudder backup identity broker", docs_url=None, redoc_url=None)

    @app.get("/healthz", tags=["meta"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/internal/backup-identities/cloudnativepg", tags=["internal"])
    async def bind_cloudnativepg(request: CloudNativePgBindingRequest) -> dict[str, str]:
        if not configured_project_id or not configured_backup_gsa:
            raise HTTPException(status_code=503, detail="backup identity broker is not configured")
        broker = GkeBackupIdentityBroker(
            project_id=configured_project_id,
            backup_service_account=configured_backup_gsa,
            iam=iam_factory(),
        )
        try:
            await broker.ensure_cnpg_binding(
                namespace=request.namespace,
                service_account_name=request.service_account_name,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"status": "bound"}

    return app


app = create_backup_identity_broker_app()
