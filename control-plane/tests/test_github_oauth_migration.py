"""Migration safety checks for persisted GitHub OAuth identities."""

from importlib import import_module
from types import SimpleNamespace

import pytest


class _Result:
    def __init__(self, value: object | None) -> None:
        self.value = value

    def scalar(self) -> object | None:
        return self.value


class _Bind:
    def __init__(self, value: object | None) -> None:
        self.value = value

    def execute(self, statement):  # noqa: ANN001
        return _Result(self.value)


def test_downgrade_refuses_to_remove_persisted_github_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    migration = import_module("migrations.versions.0003_github_oauth_identity")
    dropped: list[str] = []
    ops = SimpleNamespace(
        get_bind=lambda: _Bind(1),
        drop_index=lambda *args, **kwargs: dropped.append("index"),
        drop_column=lambda *args, **kwargs: dropped.append("column"),
    )
    monkeypatch.setattr(migration, "op", ops)

    with pytest.raises(RuntimeError, match="GitHub OAuth identities"):
        migration.downgrade()

    assert dropped == []
