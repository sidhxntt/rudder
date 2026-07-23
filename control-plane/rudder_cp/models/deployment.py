import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from rudder_cp.models.base import (
    DeploymentStatus,
    InstanceStatus,
    created_at_column,
    optional_timestamp,
    pg_enum,
    uuid_pk,
)


class Deployment(SQLModel, table=True):
    """One immutable build of one service.

    `image_tag` is never reused and never deleted. A Deployment is an artifact;
    a Domain can point at any past one. That is the whole mechanism behind
    instant rollback (D15) — rollback is an UPDATE on a Domain row, not a
    rebuild.
    """

    __tablename__ = "deployment"

    id: uuid.UUID = uuid_pk()
    service_id: uuid.UUID = Field(foreign_key="service.id", sa_type=sa.Uuid, nullable=False)
    image_tag: str | None = Field(default=None, max_length=512)
    commit_sha: str | None = Field(default=None, max_length=40)

    status: DeploymentStatus = Field(
        default=DeploymentStatus.QUEUED,
        sa_column=sa.Column(
            pg_enum(DeploymentStatus, "deployment_status"),
            nullable=False,
            index=True,
        ),
    )
    # Readable reason a deploy failed. The UI shows this verbatim.
    error_message: str | None = Field(default=None, sa_column=sa.Column(sa.Text, nullable=True))
    build_log_url: str | None = Field(default=None, max_length=512)

    created_at: datetime = created_at_column()
    became_live_at: datetime | None = optional_timestamp()


class Instance(SQLModel, table=True):
    """A running container.

    Deployment is the intent; Instance is the fact. A rolling deploy is old
    Instances draining while new Instances start, both pointing at different
    Deployments of the same Service — which is why status lives here and not on
    Deployment.
    """

    __tablename__ = "instance"

    id: uuid.UUID = uuid_pk()
    deployment_id: uuid.UUID = Field(
        foreign_key="deployment.id", sa_type=sa.Uuid, nullable=False, index=True
    )
    node_id: uuid.UUID = Field(foreign_key="node.id", sa_type=sa.Uuid, nullable=False)
    container_id: str | None = Field(default=None, max_length=64)

    status: InstanceStatus = Field(
        default=InstanceStatus.STARTING,
        sa_column=sa.Column(
            pg_enum(InstanceStatus, "instance_status"),
            nullable=False,
            index=True,
        ),
    )
    wg_ip: str | None = Field(default=None, max_length=45)

    created_at: datetime = created_at_column()
    started_at: datetime | None = optional_timestamp()
    stopped_at: datetime | None = optional_timestamp()
