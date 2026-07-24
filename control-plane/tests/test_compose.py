"""Safe Compose planning for GitHub repository imports."""

import pytest

from rudder_cp.services.compose import (
    ComposeValidationError,
    generated_compose_plan,
    parse_repository_compose,
    resolve_compose_plan,
)


class FakeRepository:
    def __init__(self, files: dict[str, str]) -> None:
        self.files = files

    async def file_at_ref(
        self, installation_id: int, repo: str, branch: str, path: str
    ) -> str | None:
        assert (installation_id, repo, branch) == (7, "acme/api", "main")
        return self.files.get(path)


def test_repository_compose_marks_only_published_service_as_public() -> None:
    plan = parse_repository_compose(
        "services:\n"
        "  web:\n"
        "    build: .\n"
        "    ports: ['3000:3000']\n"
        "  db:\n"
        "    image: postgres:16\n"
    )

    assert plan.source == "repository"
    assert plan.services["web"].public_port == 3000
    assert plan.services["db"].public_port is None
    assert "ports:" not in plan.yaml
    assert "expose:" in plan.yaml


def test_repository_compose_classifies_common_service_roles() -> None:
    plan = parse_repository_compose(
        "services:\n"
        "  web:\n"
        "    image: nginx\n"
        "    ports: [8080]\n"
        "  worker:\n"
        "    image: example/app\n"
        "    command: npm run worker\n"
        "  postgres:\n"
        "    image: postgres:16-alpine\n"
        "  prometheus:\n"
        "    image: prom/prometheus:v3\n"
        "  grafana:\n"
        "    image: grafana/grafana:11\n"
    )

    assert plan.services["web"].role == "web"
    assert plan.services["web"].is_public is True
    assert plan.services["web"].container_port == 8080
    assert plan.services["worker"].role == "worker"
    assert plan.services["worker"].is_public is False
    assert plan.services["postgres"].role == "database"
    assert plan.services["postgres"].container_port is None
    assert plan.services["prometheus"].role == "observability"
    assert plan.services["grafana"].role == "observability"


def test_repository_compose_rejects_host_bind_mounts() -> None:
    with pytest.raises(ComposeValidationError, match="host bind"):
        parse_repository_compose(
            "services:\n  web:\n    image: nginx\n    volumes: ['./:/app']\n"
        )


@pytest.mark.parametrize(
    "manifest, message",
    [
        ("services:\n  web:\n    image: nginx\n    privileged: true\n", "privileged"),
        ("services:\n  web:\n    image: nginx\n    network_mode: host\n", "network_mode"),
        ("networks: {custom: {}}\nservices:\n  web: {image: nginx}\n", "networks"),
    ],
)
def test_repository_compose_rejects_host_level_capabilities(manifest: str, message: str) -> None:
    with pytest.raises(ComposeValidationError, match=message):
        parse_repository_compose(manifest)


def test_generated_compose_uses_private_managed_addons() -> None:
    plan = generated_compose_plan({"postgres", "redis"})

    assert plan.source == "generated"
    assert plan.services["app"].public_port == 3000
    assert plan.services["postgres"].public_port is None
    assert plan.services["redis"].public_port is None
    assert "postgres-data" in plan.yaml
    assert "redis-data" in plan.yaml


@pytest.mark.parametrize(
    "addon, image, volume",
    [
        ("mysql", "mysql:8", "mysql-data"),
        ("mariadb", "mariadb:11", "mariadb-data"),
        ("mongodb", "mongo:8", "mongodb-data"),
        ("rabbitmq", "rabbitmq:4-management-alpine", "rabbitmq-data"),
        ("minio", "minio/minio", "minio-data"),
        ("qdrant", "qdrant/qdrant", "qdrant-data"),
        ("prometheus", "prom/prometheus", "prometheus-data"),
        ("grafana", "grafana/grafana", "grafana-data"),
    ],
)
def test_generated_catalog_addons_are_private_and_stateful(
    addon: str, image: str, volume: str
) -> None:
    plan = generated_compose_plan({addon})

    assert plan.services[addon].is_public is False
    assert plan.services[addon].public_port is None
    assert image in plan.yaml
    assert volume in plan.yaml
    assert "privileged:" not in plan.yaml
    assert "ports:" not in plan.yaml


async def test_resolution_prefers_repository_compose_over_generated_addons() -> None:
    plan = await resolve_compose_plan(
        FakeRepository({"compose.yml": "services:\n  api: {image: nginx, ports: [8080]}\n"}),
        installation_id=7,
        repository="acme/api",
        branch="main",
        selected_addons={"postgres"},
    )

    assert plan.source == "repository"
    assert set(plan.services) == {"api"}


async def test_resolution_generates_compose_when_repository_has_none() -> None:
    plan = await resolve_compose_plan(
        FakeRepository({}),
        installation_id=7,
        repository="acme/api",
        branch="main",
        selected_addons={"redis"},
    )

    assert plan.source == "generated"
    assert set(plan.services) == {"app", "redis"}
