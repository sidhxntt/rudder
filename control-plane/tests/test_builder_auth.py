"""Repository imports use their GitHub App installation token for checkout."""

from rudder_cp.config import Settings
from rudder_cp.services.builder import _authed_remote, _scrub


def test_github_app_token_overrides_the_legacy_install_wide_token() -> None:
    settings = Settings(github_token="legacy-token")
    remote = _authed_remote("acme/private-api", settings, "installation-token")

    assert remote == "https://x-access-token:installation-token@github.com/acme/private-api.git"


def test_scrub_removes_both_possible_git_credentials() -> None:
    settings = Settings(github_token="legacy-token")
    output = _scrub("legacy-token installation-token", settings, "installation-token")

    assert output == "*** ***"
