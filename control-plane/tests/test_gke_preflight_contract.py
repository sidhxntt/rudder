"""Regression coverage for the read-only GKE capacity preflight."""

from __future__ import annotations

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_gke_preflight_checks_live_cluster_identity_and_gke_cpu_quota() -> None:
    """Do not allow workload-pool rollout to discover quota mid-apply."""

    preflight = (REPOSITORY_ROOT / "infra/gcp/scripts/preflight-gke.sh").read_text(
        encoding="utf-8"
    )

    assert '"${RUDDER_GCP_PROJECT:?Set RUDDER_GCP_PROJECT}"' in preflight
    assert '"${RUDDER_GCP_REGION:?Set RUDDER_GCP_REGION}"' in preflight
    assert '"${RUDDER_GKE_CLUSTER:?Set RUDDER_GKE_CLUSTER}"' in preflight
    assert "gcloud compute project-info describe" in preflight
    assert "gcloud auth application-default print-access-token" in preflight
    assert "gcloud auth application-default login" in preflight
    assert 'select(.metric == "CPUS_ALL_REGIONS")' in preflight
    assert "tonumber | floor" in preflight
    assert "gcloud container clusters describe" in preflight
    assert ".workloadIdentityConfig.workloadPool" in preflight
    assert "RUDDER_REQUIRED_GKE_CPUS" in preflight
    assert "Request a project-wide CPUS_ALL_REGIONS quota increase" in preflight
