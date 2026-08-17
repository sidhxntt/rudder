"""Regression coverage for the full local migration chain.

Production runs the same revisions against CloudNativePG/PostgreSQL.  SQLite
is deliberately supported for the hermetic development and image smoke path,
so PostgreSQL-only enum DDL must be guarded by its dialect.
"""

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config

from rudder_cp.config import get_settings


def _alembic_config() -> Config:
    control_plane = Path(__file__).parents[1]
    config = Config(str(control_plane / "alembic.ini"))
    config.set_main_option("script_location", str(control_plane / "migrations"))
    return config


def test_full_migration_chain_runs_on_sqlite(tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """A fresh local database reaches head without PostgreSQL-only SQL."""

    database_url = f"sqlite:///{tmp_path / 'migrations-at-head.db'}"
    monkeypatch.setenv("RUDDER_DATABASE_URL", database_url)
    get_settings.cache_clear()

    try:
        command.upgrade(_alembic_config(), "head")
        engine = sa.create_engine(database_url)
        try:
            assert sa.inspect(engine).has_table("user")
            assert sa.inspect(engine).has_table("service_operations_state")
            assert sa.inspect(engine).has_table("service_managed_capabilities")
        finally:
            engine.dispose()
    finally:
        get_settings.cache_clear()
