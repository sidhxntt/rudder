import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from rudder_cp.models.base import DomainTargetType, created_at_column, pg_enum, uuid_pk


class Domain(SQLModel, table=True):
    """The routing unit. D15.

    Traefik config is generated from Domain rows, never from Service rows. One
    router per Domain. Phase 1 only ever creates system domains, one per
    service, so behaviour is identical to routing-per-service — but the routing
    code reads the right table from day one, which is what makes previews,
    immutable deployment URLs, custom domains, and instant rollback possible
    without a rewrite.

    Exactly one of service_id / deployment_id is non-null, enforced by a CHECK
    constraint rather than by application code.
    """

    __tablename__ = "domain"
    __table_args__ = (
        sa.CheckConstraint(
            "(service_id IS NOT NULL AND deployment_id IS NULL)"
            " OR (service_id IS NULL AND deployment_id IS NOT NULL)",
            name="ck_domain_exactly_one_target",
        ),
    )

    id: uuid.UUID = uuid_pk()
    hostname: str = Field(sa_column=sa.Column(sa.String(255), unique=True, nullable=False))
    environment_id: uuid.UUID = Field(
        foreign_key="environment.id", sa_type=sa.Uuid, nullable=False
    )

    target_type: DomainTargetType = Field(
        default=DomainTargetType.SERVICE,
        sa_column=sa.Column(pg_enum(DomainTargetType, "domain_target_type"), nullable=False),
    )
    # Set when target_type=service. Follows whatever Deployment is live.
    service_id: uuid.UUID | None = Field(default=None, foreign_key="service.id", sa_type=sa.Uuid)
    # Set when target_type=deployment. Pinned to one immutable build forever.
    deployment_id: uuid.UUID | None = Field(
        default=None, foreign_key="deployment.id", sa_type=sa.Uuid
    )

    # True for the auto-generated {service}.{env}.{base_domain}. System domains
    # are created and deleted with their service; user domains are not.
    is_system: bool = Field(default=False, nullable=False)
    tls_enabled: bool = Field(default=False, nullable=False)

    created_at: datetime = created_at_column()
