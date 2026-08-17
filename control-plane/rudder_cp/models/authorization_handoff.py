"""Durable browser authorization handoffs shared by every control-plane replica."""

from datetime import datetime

import sqlalchemy as sa
from sqlmodel import Field, SQLModel

from rudder_cp.models.base import created_at_column


class AuthorizationHandoff(SQLModel, table=True):
    """A short-lived opaque request that may yield a token exactly once."""

    __tablename__ = "authorization_handoff"

    id: str = Field(sa_column=sa.Column(sa.String(length=255), primary_key=True))
    token: str | None = Field(default=None, sa_column=sa.Column(sa.Text, nullable=True))
    expires_at: datetime = Field(
        sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False, index=True)
    )
    created_at: datetime = created_at_column()
