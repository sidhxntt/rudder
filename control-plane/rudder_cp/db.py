"""Engine and session dependency. Tables live in rudder_cp.models."""

from collections.abc import Generator

from sqlalchemy import Engine
from sqlmodel import Session, create_engine

from rudder_cp.config import get_settings

_engine: Engine | None = None


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = create_engine(get_settings().sqlalchemy_database_url, pool_pre_ping=True)
    return _engine


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session
