"""Migration coverage for immutable Compose import metadata."""

from pathlib import Path
from uuid import uuid4

import sqlalchemy as sa
from alembic import command

from tests.test_github_oauth_migration import _alembic_config


def test_alembic_backfills_compose_import_metadata(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite:///{tmp_path / 'compose-import.db'}"
    monkeypatch.setenv("RUDDER_DATABASE_URL", database_url)
    config = _alembic_config()

    command.upgrade(config, "0003")
    engine = sa.create_engine(database_url)
    project_id = uuid4()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "INSERT INTO github_import "
                "(id, installation_id, repository, branch, project_id, app_service_id, created_at) "
                "VALUES (:id, 1, 'acme/api', 'main', :project_id, :app_service_id, "
                "CURRENT_TIMESTAMP)"
            ),
            {"id": str(uuid4()), "project_id": str(project_id), "app_service_id": str(uuid4())},
        )

    command.upgrade(config, "0004")
    with engine.connect() as connection:
        row = connection.execute(
            sa.text(
                "SELECT compose_source, compose_manifest, compose_project_name "
                "FROM github_import"
            )
        ).one()
        indexes = sa.inspect(connection).get_indexes("github_import")

    assert row == ("generated", "services: {}\n", f"rudder-{project_id.hex}")
    assert any(
        index["name"] == "ix_github_import_compose_project_name" and index["unique"]
        for index in indexes
    )
    engine.dispose()
