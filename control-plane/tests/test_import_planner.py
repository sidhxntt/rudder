"""Tests for Node repository dependency proposals used by GitHub imports."""

from rudder_cp.services.imports import detect_node_addons
from rudder_cp.services.processes import detect_processes


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


def test_manifest_proposes_catalog_addons_from_exact_clients() -> None:
    proposal = detect_node_addons(
        {
            "dependencies": {
                "mysql2": "^3.0.0",
                "mongoose": "^8.0.0",
                "amqplib": "^0.10.0",
                "nats": "^2.0.0",
                "meilisearch": "^0.42.0",
                "minio": "^8.0.0",
                "@qdrant/js-client-rest": "^1.0.0",
            }
        },
        existing_variable_keys=set(),
    )

    assert proposal.addons == (
        "mysql",
        "mongodb",
        "rabbitmq",
        "nats",
        "meilisearch",
        "minio",
        "qdrant",
    )


def test_process_detection_uses_known_scripts_and_procfile_entries() -> None:
    processes = detect_processes(
        {
            "scripts": {
                "start": "node server.js",
                "worker": "node worker.js",
                "queue": "node queue.js",
                "cron": "node cron.js",
                "lint": "eslint .",
            }
        },
        "web: npm run start\nworker: npm run worker\nclock: npm run cron\n",
    )

    assert [(process.role, process.command) for process in processes] == [
        ("web", "npm run start"),
        ("worker", "npm run worker"),
        ("scheduler", "npm run cron"),
    ]
