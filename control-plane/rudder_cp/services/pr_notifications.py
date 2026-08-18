"""Outbox delivery for PR-environment readiness comments."""

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from rudder_cp.config import Settings
from rudder_cp.models import (
    Deployment,
    Domain,
    Environment,
    GitHubImport,
    PullRequestNotification,
    Service,
)
from rudder_cp.services.github_app import GitHubAppClient, GitHubAppError

log = logging.getLogger(__name__)


def enqueue_ready_notification(
    session: Session, *, deployment: Deployment, service: Service, settings: Settings
) -> PullRequestNotification | None:
    """Persist a ready comment before returning a deployment as live.

    The unique deployment key means recovery/replay may call this repeatedly
    without creating duplicate GitHub comments.
    """

    environment = session.get(Environment, service.environment_id)
    if environment is None or environment.github_pr_number is None:
        return None
    imported = session.exec(
        select(GitHubImport).where(
            GitHubImport.project_id == environment.project_id,
            GitHubImport.app_service_id == service.id,
        )
    ).first()
    domain = session.exec(
        select(Domain)
        .where(Domain.service_id == service.id, Domain.is_system.is_(True))
        .order_by(Domain.created_at)
    ).first()
    if imported is None or domain is None:
        return None
    existing = session.exec(
        select(PullRequestNotification).where(
            PullRequestNotification.deployment_id == deployment.id
        )
    ).first()
    if existing is not None:
        return existing
    scheme = "https" if settings.tls_mode == "acme" else "http"
    notification = PullRequestNotification(
        deployment_id=deployment.id,
        installation_id=imported.installation_id,
        repository=imported.repository,
        pull_request_number=environment.github_pr_number,
        body=f"Rudder PR environment ready: {scheme}://{domain.hostname}",
    )
    session.add(notification)
    try:
        session.commit()
    except IntegrityError:
        # A second recovery worker won the race. Its durable row is the one
        # the reconciler will deliver.
        session.rollback()
        return session.exec(
            select(PullRequestNotification).where(
                PullRequestNotification.deployment_id == deployment.id
            )
        ).one()
    session.refresh(notification)
    return notification


async def deliver_due_notifications(
    session: Session, *, settings: Settings, now: datetime | None = None
) -> int:
    """Attempt all due comments, retaining failed rows for exponential retry."""

    current = now or datetime.now(UTC)
    due = session.exec(
        select(PullRequestNotification).where(
            PullRequestNotification.sent_at.is_(None),
            PullRequestNotification.next_attempt_at <= current,
        )
    ).all()
    sent = 0
    github = GitHubAppClient(settings)
    for notification in due:
        try:
            await github.comment_on_pull_request(
                notification.installation_id,
                notification.repository,
                notification.pull_request_number,
                notification.body,
            )
        except GitHubAppError as exc:
            notification.attempt_count += 1
            notification.last_error = str(exc)
            # Retry at 10s, 20s, 40s … capped at five minutes. The reconciler
            # cadence bounds when the next due attempt is observed.
            delay_seconds = min(300, 10 * 2 ** min(notification.attempt_count - 1, 5))
            notification.next_attempt_at = current + timedelta(seconds=delay_seconds)
            session.add(notification)
            log.warning(
                "could not post readiness notification for deployment %s (attempt %s): %s",
                notification.deployment_id,
                notification.attempt_count,
                exc,
            )
            continue
        notification.sent_at = current
        notification.last_error = None
        session.add(notification)
        sent += 1
    session.commit()
    return sent
