import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from rudder_cp.models.base import created_at_column, uuid_pk


class User(SQLModel, table=True):
    """Single-tenant: exactly one row, seeded from .env on first boot.

    There is no signup and no RBAC — both are explicit non-goals.
    """

    __tablename__ = "user"

    id: uuid.UUID = uuid_pk()
    email: str = Field(sa_column=sa.Column(sa.String(255), unique=True, nullable=False))
    password_hash: str = Field(nullable=False)
    github_id: int | None = Field(
        default=None,
        sa_column=sa.Column(sa.Integer, unique=True, index=True, nullable=True),
    )
    github_login: str | None = Field(
        default=None,
        sa_column=sa.Column(sa.String(255), nullable=True),
    )
    created_at: datetime = created_at_column()
