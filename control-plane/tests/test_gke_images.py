"""Production image-reference invariants for the GKE runtime."""

import pytest

from rudder_cp.services.builder import validate_gke_image


def test_gke_release_requires_an_artifact_registry_digest() -> None:
    with pytest.raises(ValueError, match="immutable digest"):
        validate_gke_image(
            "asia-south1-docker.pkg.dev/invytt-2483d/rudder/api:latest"
        )


def test_gke_release_accepts_an_artifact_registry_digest() -> None:
    image = (
        "asia-south1-docker.pkg.dev/invytt-2483d/rudder/api"
        "@sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    )

    assert validate_gke_image(image) == image
