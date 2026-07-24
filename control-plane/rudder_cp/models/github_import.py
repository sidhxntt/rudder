"""Persisted state for a repository import and its managed add-ons."""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from rudder_cp.models.base import created_at_column, uuid_pk


class GitHubImport(SQLModel, table=True):
    """One confirmed GitHub repository import.

    The service ids make the import progress API a projection of the actual
    deployment rows rather than a second, eventually-consistent state machine.
    """

    __tablename__ = "github_import"

    id: uuid.UUID = uuid_pk()
    installation_id: int = Field(nullable=False)
    repository: str = Field(sa_column=sa.Column(sa.String(255), nullable=False))
    branch: str = Field(sa_column=sa.Column(sa.String(255), nullable=False))
    # The resolved Compose document is immutable input to a deployment.  We
    # keep it beside the import instead of reconstructing it from mutable
    # repository state when a deploy is retried.
    compose_source: str = Field(sa_column=sa.Column(sa.String(32), nullable=False))
    compose_manifest: str = Field(sa_column=sa.Column(sa.Text(), nullable=False))
    compose_project_name: str = Field(
        sa_column=sa.Column(sa.String(63), nullable=False, unique=True, index=True)
    )
    project_id: uuid.UUID = Field(foreign_key="project.id", sa_type=sa.Uuid, nullable=False)
    app_service_id: uuid.UUID = Field(foreign_key="service.id", sa_type=sa.Uuid, nullable=False)
    postgres_service_id: uuid.UUID | None = Field(
        default=None, foreign_key="service.id", sa_type=sa.Uuid
    )
    redis_service_id: uuid.UUID | None = Field(
        default=None, foreign_key="service.id", sa_type=sa.Uuid
    )
    created_at: datetime = created_at_column()


class GitHubImportService(SQLModel, table=True):
    """Maps one Rudder service to a service in its immutable Compose release."""

    __tablename__ = "github_import_service"
    __table_args__ = (
        sa.UniqueConstraint(
            "github_import_id", "compose_service", name="uq_import_compose_service"
        ),
        sa.UniqueConstraint("service_id", name="uq_import_service"),
    )

    id: uuid.UUID = uuid_pk()
    github_import_id: uuid.UUID = Field(
        foreign_key="github_import.id", sa_type=sa.Uuid, nullable=False, index=True
    )
    service_id: uuid.UUID = Field(foreign_key="service.id", sa_type=sa.Uuid, nullable=False)
    compose_service: str = Field(sa_column=sa.Column(sa.String(63), nullable=False))
    role: str = Field(sa_column=sa.Column(sa.String(32), nullable=False))
    is_public: bool = Field(default=False, nullable=False)
    # The candidate Compose container that currently serves this graph member.
    # This is populated only after the owner release is healthy, so a failed
    # candidate cannot move a child service's public route.
    container_id: str | None = Field(default=None, sa_column=sa.Column(sa.String(64)))
    created_at: datetime = created_at_column()
