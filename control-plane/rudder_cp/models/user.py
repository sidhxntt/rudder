import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from rudder_cp.models.base import created_at_column, uuid_pk


class User(SQLModel, table=True):
    """A local account, optionally linked to one durable GitHub identity.

    Password login remains available for the configured seeded admin. GitHub
    OAuth users are linked only by GitHub's immutable numeric ``github_id``;
    login names and email addresses are mutable profile data.
    """

    __tablename__ = "user"

    id: uuid.UUID = uuid_pk()
    email: str = Field(sa_column=sa.Column(sa.String(255), unique=True, nullable=False))
    password_hash: str = Field(nullable=False)
    github_id: int | None = Field(
        default=None,
        sa_column=sa.Column(sa.BigInteger, unique=True, index=True, nullable=True),
    )
    github_login: str | None = Field(
        default=None,
        sa_column=sa.Column(sa.String(255), nullable=True),
    )
    # GitHub's immutable profile image URL is display-only account metadata.
    # It never grants access and is only returned to the authenticated user
    # through /auth/me.
    github_avatar_url: str | None = Field(
        default=None,
        sa_column=sa.Column(sa.String(2048), nullable=True),
    )
    created_at: datetime = created_at_column()
