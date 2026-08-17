import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from rudder_cp.models.base import created_at_column, uuid_pk


class Project(SQLModel, table=True):
    __tablename__ = "project"

    id: uuid.UUID = uuid_pk()
    name: str = Field(sa_column=sa.Column(sa.String(64), nullable=False))
    owner_id: uuid.UUID = Field(foreign_key="user.id", sa_type=sa.Uuid, nullable=False)
    created_at: datetime = created_at_column()


class Environment(SQLModel, table=True):
    """A project's isolated copy of a service graph.

    Runtime isolation is provided by the namespace and NetworkPolicies rendered
    by the Kubernetes runtime, not a host-level mesh CIDR.
    """

    __tablename__ = "environment"
    __table_args__ = (
        sa.UniqueConstraint("project_id", "name", name="uq_environment_project_name"),
    )

    id: uuid.UUID = uuid_pk()
    project_id: uuid.UUID = Field(foreign_key="project.id", sa_type=sa.Uuid, nullable=False)
    name: str = Field(sa_column=sa.Column(sa.String(32), nullable=False))
    is_production: bool = Field(default=False, nullable=False)
    created_at: datetime = created_at_column()
