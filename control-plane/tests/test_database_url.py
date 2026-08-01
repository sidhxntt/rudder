"""Database URL compatibility at the Kubernetes configuration boundary."""

from rudder_cp.config import Settings


def test_sqlalchemy_database_url_normalises_a_cloudnativepg_uri() -> None:
    """CNPG publishes PostgreSQL URIs without SQLAlchemy's driver suffix."""

    settings = Settings(database_url="postgresql://app:secret@rudder-db-rw:5432/app")

    assert (
        settings.sqlalchemy_database_url
        == "postgresql+psycopg://app:secret@rudder-db-rw:5432/app"
    )


def test_sqlalchemy_database_url_leaves_existing_driver_and_sqlite_urls_alone() -> None:
    assert (
        Settings(database_url="postgresql+psycopg://app:secret@db/app").sqlalchemy_database_url
        == "postgresql+psycopg://app:secret@db/app"
    )
    assert Settings(database_url="sqlite:///rudder.db").sqlalchemy_database_url == "sqlite:///rudder.db"
