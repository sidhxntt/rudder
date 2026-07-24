"""Tests for Node repository dependency proposals used by GitHub imports."""

from rudder_cp.services.imports import detect_node_addons


def test_node_manifest_proposes_postgres_and_redis_when_urls_are_absent() -> None:
    proposal = detect_node_addons(
        {
            "dependencies": {
                "express": "^5.0.0",
                "pg": "^8.13.0",
                "ioredis": "^5.4.0",
            }
        },
        existing_variable_keys=set(),
    )

    assert proposal.is_node_app is True
    assert proposal.addons == ("postgres", "redis")
    assert proposal.externally_managed == ()


def test_node_manifest_does_not_propose_addon_when_matching_url_exists() -> None:
    proposal = detect_node_addons(
        {"dependencies": {"express": "^5.0.0", "pg": "^8.13.0", "redis": "^4.7.0"}},
        existing_variable_keys={"DATABASE_URL"},
    )

    assert proposal.addons == ("redis",)
    assert proposal.externally_managed == ("postgres",)


def test_manifest_without_supported_clients_is_not_an_addon_proposal() -> None:
    proposal = detect_node_addons(
        {"dependencies": {"express": "^5.0.0", "lodash": "^4.17.21"}},
        existing_variable_keys=set(),
    )

    assert proposal.is_node_app is True
    assert proposal.addons == ()
