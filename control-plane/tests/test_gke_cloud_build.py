"""Production image builds use Cloud Build, not the local Compose builder."""

from __future__ import annotations

from uuid import uuid4

import pytest

from rudder_cp.config import Settings
from rudder_cp.logs.store import BuildLogStore
from rudder_cp.services import builder
from rudder_cp.services.builder import BuildRequest


def test_cloud_build_operation_uses_metadata_build_id() -> None:
    """Cloud Build create returns a long-running Operation, not a Build."""
    payload = {"metadata": {"build": {"id": "cloud-build-123"}}}

    assert builder._cloud_build_id(payload) == "cloud-build-123"


@pytest.mark.asyncio
async def test_gke_build_uses_cloud_build_instead_of_local_buildkit(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A GKE release must never dial the local Compose-only ``registry`` host."""

    sha = "a" * 40
    request = BuildRequest(
        deployment_id=uuid4(),
        service_id=uuid4(),
        source_repo="acme/shop",
        source_branch="main",
        commit_sha=sha,
        dockerfile_path=None,
        container_port=3000,
        start_command=None,
    )
    settings = Settings(
        runtime="kubernetes",
        kubernetes_target="gke",
        base_domain="rudder.invytt.com",
        kubernetes_public_domain="rudder.invytt.com",
        kubernetes_certificate_issuer="rudder-letsencrypt-prod",
        registry="asia-south1-docker.pkg.dev/invytt-2483d/rudder",
        gcp_project_id="invytt-2483d",
        gcp_region="asia-south1",
        gcp_build_source_bucket="invytt-2483d-rudder-build-source",
        gcp_build_logs_bucket="invytt-2483d-rudder-build-logs",
        gcp_build_service_account="rudder-build@invytt-2483d.iam.gserviceaccount.com",
    )
    store = BuildLogStore(tmp_path / "logs")

    async def fake_clone(_request, _sha, repo_dir, _store, _settings) -> None:
        repo_dir.mkdir(parents=True)
        (repo_dir / "package.json").write_text(
            '{"scripts":{"start":"node index.js"}}', encoding="utf-8"
        )
        (repo_dir / "index.js").write_text("console.log('ready')\n", encoding="utf-8")

    async def local_buildkit_must_not_run(*_args, **_kwargs):
        raise AssertionError("GKE must not use the local BuildKit endpoint")

    called: dict[str, object] = {}

    async def fake_cloud_build(*, context, dockerfile_name, image_tag, **_kwargs) -> str:
        called.update(context=context, dockerfile_name=dockerfile_name, image_tag=image_tag)
        return "sha256:" + "b" * 64

    monkeypatch.setattr(builder, "_clone_at_sha", fake_clone)
    monkeypatch.setattr(builder, "_buildctl", local_buildkit_must_not_run)
    monkeypatch.setattr(builder, "_cloud_build", fake_cloud_build, raising=False)

    result = await builder.build_image(request, store, settings)

    assert result.commit_sha == sha
    assert result.image_tag == (
        "asia-south1-docker.pkg.dev/invytt-2483d/rudder/"
        f"{request.service_id}@sha256:{'b' * 64}"
    )
    assert called["context"].name == "repo"
    assert called["dockerfile_name"] == "Dockerfile"


@pytest.mark.asyncio
async def test_cloud_build_token_failure_does_not_mask_the_identity_error(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Workload Identity failures should surface, not crash cleanup first."""

    request = BuildRequest(
        deployment_id=uuid4(),
        service_id=uuid4(),
        source_repo="acme/shop",
        source_branch="main",
        commit_sha="a" * 40,
        dockerfile_path=None,
        container_port=3000,
        start_command=None,
    )
    settings = Settings(
        runtime="kubernetes",
        kubernetes_target="gke",
        base_domain="rudder.invytt.com",
        kubernetes_public_domain="rudder.invytt.com",
        kubernetes_certificate_issuer="rudder-letsencrypt-prod",
        registry="asia-south1-docker.pkg.dev/invytt-2483d/rudder",
        gcp_project_id="invytt-2483d",
        gcp_region="asia-south1",
        gcp_build_source_bucket="invytt-2483d-rudder-build-source",
        gcp_build_logs_bucket="invytt-2483d-rudder-build-logs",
        gcp_build_service_account="rudder-build@invytt-2483d.iam.gserviceaccount.com",
    )
    context = tmp_path / "repo"
    context.mkdir()
    (context / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")

    async def no_identity_token() -> str:
        raise builder.BuildFailed(
            "Could not obtain a Workload Identity access token for Cloud Build."
        )

    monkeypatch.setattr(builder, "_gcp_access_token", no_identity_token)

    with pytest.raises(builder.BuildFailed, match="Workload Identity access token"):
        await builder._cloud_build(
            request=request,
            context=context,
            dockerfile_name="Dockerfile",
            image_tag="asia-south1-docker.pkg.dev/invytt-2483d/rudder/shop:sha",
            store=BuildLogStore(tmp_path / "logs"),
            settings=settings,
        )

    assert not (context.parent / "source.tar.gz").exists()
