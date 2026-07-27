"""GitHub webhook.

The signature check is the only thing standing between this endpoint and anyone
on the internet queueing builds of arbitrary commits, so it runs before the body
is interpreted, and it is a constant-time comparison.
"""

import hashlib
import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Request, status
from sqlmodel import Session, select

from rudder_cp.config import get_settings
from rudder_cp.db import get_engine
from rudder_cp.models import Deployment, DeploymentStatus, Service

log = logging.getLogger("rudder_cp.webhooks")

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/github", status_code=status.HTTP_202_ACCEPTED)
async def github_push(
    request: Request,
    x_hub_signature_256: str | None = Header(default=None),
    x_github_event: str | None = Header(default=None),
) -> dict[str, object]:
    settings = get_settings()
    body = await request.body()

    if not settings.github_webhook_secret:
        # Refuse rather than accepting unsigned pushes. An unconfigured secret
        # is a misconfiguration, not a reason to trust the caller.
        raise HTTPException(
            status_code=503,
            detail={
                "code": "webhook_not_configured",
                "message": "RUDDER_GITHUB_WEBHOOK_SECRET is not set.",
                "details": {},
            },
        )
    if not _signature_ok(body, x_hub_signature_256, settings.github_webhook_secret):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "bad_signature",
                "message": "Webhook signature verification failed.",
                "details": {},
            },
        )

    if x_github_event == "ping":
        return {"queued": [], "detail": "pong"}
    if x_github_event != "push":
        return {"queued": [], "detail": f"ignored event: {x_github_event}"}

    payload = await request.json()
    repo = str(payload.get("repository", {}).get("full_name", ""))
    ref = str(payload.get("ref", ""))
    sha = payload.get("after")
    if not ref.startswith("refs/heads/"):
        return {"queued": [], "detail": f"ignored ref: {ref}"}
    branch = ref.removeprefix("refs/heads/")

    # A deleted branch reports an all-zero SHA. There is nothing to build.
    if not sha or set(str(sha)) == {"0"}:
        return {"queued": [], "detail": "branch deleted"}

    queued: list[str] = []
    skipped: list[str] = []
    with Session(get_engine()) as session:
        services = session.exec(
            select(Service).where(
                Service.source_repo == repo,
                Service.source_branch == branch,
            )
        ).all()
        for service in services:
            # GitHub retries deliveries when it did not observe our 202. A
            # commit is immutable, so creating a second deployment for this
            # service + SHA would rebuild identical code and can race traffic
            # changes. Users can still explicitly redeploy from the UI if a
            # failed commit needs another attempt.
            existing = session.exec(
                select(Deployment.id).where(
                    Deployment.service_id == service.id,
                    Deployment.commit_sha == str(sha),
                )
            ).first()
            if existing is not None:
                skipped.append("already queued for this commit")
                continue
            deployment = Deployment(
                service_id=service.id,
                commit_sha=str(sha),
                status=DeploymentStatus.QUEUED,
            )
            session.add(deployment)
            session.commit()
            session.refresh(deployment)
            queued.append(str(deployment.id))

    log.info(
        "push %s@%s -> queued %d deployment(s), skipped %d duplicate(s)",
        repo,
        branch,
        len(queued),
        len(skipped),
    )
    return {"queued": queued, "skipped": skipped, "repo": repo, "branch": branch}


def _signature_ok(body: bytes, header: str | None, secret: str) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.removeprefix("sha256="))
