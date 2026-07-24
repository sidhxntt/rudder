"""Integration checks for persisted GitHub OAuth identity migrations."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from rudder_cp.config import get_settings


def _alembic_config() -> Config:
    control_plane = Path(__file__).parents[1]
    config = Config(str(control_plane / "alembic.ini"))
    config.set_main_option("script_location", str(control_plane / "migrations"))
    return config


def _insert_user(connection, *, github_id: int | None, github_login: str | None) -> None:  # noqa: ANN001
    connection.execute(
        sa.text(
            'INSERT INTO "user" '
            "(id, email, password_hash, created_at, github_id, github_login) "
            "VALUES (:id, :email, :password_hash, :created_at, :github_id, :github_login)"
        ),
        {
            "id": str(uuid4()),
            "email": f"{uuid4()}@example.test",
            "password_hash": "not-a-real-hash",
            "created_at": datetime.now(UTC),
            "github_id": github_id,
            "github_login": github_login,
        },
    )


def test_alembic_migrates_github_identity_columns_and_guards_downgrade(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url = f"sqlite:///{tmp_path / 'oauth-migration.db'}"
    monkeypatch.setenv("RUDDER_DATABASE_URL", database_url)
    get_settings.cache_clear()
    config = _alembic_config()

    try:
        command.upgrade(config, "0002")
        command.upgrade(config, "0003")

        engine = sa.create_engine(database_url)
        with engine.begin() as connection:
            columns = {
                column["name"]: column
                for column in sa.inspect(connection).get_columns("user")
            }
            indexes = sa.inspect(connection).get_indexes("user")
            assert columns["github_id"]["type"].__class__.__name__.upper() == "BIGINT"
            assert columns["github_login"]["type"].length == 255
            assert any(
                index["name"] == "ix_user_github_id" and index["unique"] for index in indexes
            )

            _insert_user(connection, github_id=None, github_login="octocat")

        with pytest.raises(RuntimeError, match="GitHub OAuth identities"):
            command.downgrade(config, "0002")

        with engine.begin() as connection:
            connection.execute(sa.text('DELETE FROM "user"'))
            _insert_user(connection, github_id=4_294_967_297, github_login=None)

        with pytest.raises(RuntimeError, match="GitHub OAuth identities"):
            command.downgrade(config, "0002")

        with engine.begin() as connection:
            connection.execute(sa.text('DELETE FROM "user"'))
            _insert_user(connection, github_id=1, github_login="octocat")
            with pytest.raises(sa.exc.IntegrityError):
                _insert_user(connection, github_id=1, github_login="octocat-two")

        with engine.begin() as connection:
            connection.execute(sa.text('DELETE FROM "user"'))
        command.downgrade(config, "0002")
        assert {column["name"] for column in sa.inspect(engine).get_columns("user")} == {
            "id",
            "email",
            "password_hash",
            "created_at",
        }
        engine.dispose()
    finally:
        get_settings.cache_clear()
