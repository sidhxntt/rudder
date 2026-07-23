import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from rudder_cp.models.base import ServiceKind, created_at_column, pg_enum, uuid_pk


class Service(SQLModel, table=True):
    __tablename__ = "service"
    __table_args__ = (
        sa.UniqueConstraint("environment_id", "name", name="uq_service_environment_name"),
    )

    id: uuid.UUID = uuid_pk()
    environment_id: uuid.UUID = Field(
        foreign_key="environment.id", sa_type=sa.Uuid, nullable=False
    )
    # Becomes a hostname label, so D9 validation applies at the API boundary.
    name: str = Field(sa_column=sa.Column(sa.String(32), nullable=False))
    kind: ServiceKind = Field(
        default=ServiceKind.APP,
        sa_column=sa.Column(pg_enum(ServiceKind, "service_kind"), nullable=False),
    )

    source_repo: str | None = Field(default=None, max_length=255)
    source_branch: str = Field(default="main", max_length=255)
    dockerfile_path: str | None = Field(default=None, max_length=255)
    build_config: dict[str, Any] = Field(
        default_factory=dict, sa_column=sa.Column(sa.JSON, nullable=False)
    )

    start_command: str | None = Field(default=None, max_length=512)

    # D1: the port the app listens on. Traefik routes here.
    container_port: int = Field(default=8080, nullable=False)
    health_check_path: str = Field(default="/", max_length=255)
    # Defaults to container_port when null — resolved in the deploy path, not here.
    health_check_port: int | None = Field(default=None)

    cpu_limit: float = Field(default=1.0, nullable=False)
    memory_limit_mb: int = Field(default=512, nullable=False)
    replica_count: int = Field(default=1, nullable=False)

    # D6: UI-only metadata. The DB owns layout; no declarative layer manages it.
    canvas_x: float = Field(default=0.0, nullable=False)
    canvas_y: float = Field(default=0.0, nullable=False)

    created_at: datetime = created_at_column()


class Variable(SQLModel, table=True):
    """An env var for one service.

    The plaintext value never leaves this table. `value_encrypted` is Fernet
    ciphertext (D13, MultiFernet so keys can rotate) and API schemas must never
    expose it — that is why schemas are separate from tables.
    """

    __tablename__ = "variable"
    __table_args__ = (sa.UniqueConstraint("service_id", "key", name="uq_variable_service_key"),)

    id: uuid.UUID = uuid_pk()
    service_id: uuid.UUID = Field(foreign_key="service.id", sa_type=sa.Uuid, nullable=False)
    key: str = Field(sa_column=sa.Column(sa.String(255), nullable=False))
    value_encrypted: bytes = Field(sa_column=sa.Column(sa.LargeBinary, nullable=False))
    # True when the plaintext is a reference like "${{postgres.DATABASE_URL}}",
    # resolved against sibling services at deploy time.
    is_reference: bool = Field(default=False, nullable=False)
    created_at: datetime = created_at_column()


class Volume(SQLModel, table=True):
    """Persistent storage for one service.

    A volume lives on exactly one node, which pins the service to that node.
    The Phase 2 scheduler must honour that pin — it is the reason node_id is
    here in Phase 1 rather than being added later.
    """

    __tablename__ = "volume"

    id: uuid.UUID = uuid_pk()
    service_id: uuid.UUID = Field(foreign_key="service.id", sa_type=sa.Uuid, nullable=False)
    mount_path: str = Field(max_length=255, nullable=False)
    size_mb: int = Field(default=1024, nullable=False)
    node_id: uuid.UUID | None = Field(default=None, foreign_key="node.id", sa_type=sa.Uuid)
    created_at: datetime = created_at_column()
