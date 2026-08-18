"""Durable delivery state for pull-request environment notifications."""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from rudder_cp.models.base import created_at_column, optional_timestamp, uuid_pk


class PullRequestNotification(SQLModel, table=True):
    """One idempotent GitHub-ready comment for a live preview deployment.

    The deployment worker only records intent.  The reconciler owns delivery,
    so a GitHub API outage cannot turn a successful preview deploy into a
    permanently missing notification.
    """

    __tablename__ = "pull_request_notification"
    __table_args__ = (sa.UniqueConstraint("deployment_id", name="uq_pr_notification_deployment"),)

    id: uuid.UUID = uuid_pk()
    deployment_id: uuid.UUID = Field(
        foreign_key="deployment.id", sa_type=sa.Uuid, nullable=False, index=True
    )
    installation_id: int = Field(nullable=False)
    repository: str = Field(max_length=255, nullable=False)
    pull_request_number: int = Field(nullable=False)
    body: str = Field(sa_column=sa.Column(sa.Text, nullable=False))
    attempt_count: int = Field(default=0, nullable=False)
    next_attempt_at: datetime = created_at_column()
    last_error: str | None = Field(default=None, sa_column=sa.Column(sa.Text, nullable=True))
    sent_at: datetime | None = optional_timestamp()
    created_at: datetime = created_at_column()
