"""Regression coverage for GKE system and platform pool scheduling.

GKE system add-ons such as CoreDNS do not tolerate Rudder-specific taints.  The
system pool must therefore remain available to them, while platform workloads
remain isolated on the tainted platform pool through explicit tolerations.
"""

from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _node_pool_block(terraform: str, name: str) -> str:
    marker = f'resource "google_container_node_pool" "{name}"'
    start = terraform.index(marker)
    next_resource = terraform.find('\nresource ', start + len(marker))
    return terraform[start : next_resource if next_resource != -1 else None]


def test_system_pool_is_untainted_for_gke_managed_components() -> None:
    """CoreDNS and other GKE add-ons need a schedulable system pool."""

    cluster = (REPOSITORY_ROOT / "infra/gcp/terraform/cluster.tf").read_text(
        encoding="utf-8"
    )
    system = _node_pool_block(cluster, "system")

    assert '"rudder.pool" = "system"' in system
    assert "taint {" not in system


def test_platform_workloads_explicitly_tolerate_the_platform_taint() -> None:
    """Rudder's control-plane edge remains isolated from customer workloads."""

    cluster = (REPOSITORY_ROOT / "infra/gcp/terraform/cluster.tf").read_text(
        encoding="utf-8"
    )
    platform = _node_pool_block(cluster, "platform")
    assert '"rudder.pool" = "platform"' in platform
    assert 'value  = "platform"' in platform
    assert 'effect = "NO_SCHEDULE"' in platform

    control_plane = (
        REPOSITORY_ROOT / "infra/kubernetes/platform/control-plane.yaml"
    ).read_text(encoding="utf-8")
    assert "rudder.pool: platform" in control_plane
    assert "tolerations:" in control_plane
    assert "value: platform" in control_plane
    assert "effect: NoSchedule" in control_plane

    bootstrap = (
        REPOSITORY_ROOT / "infra/gcp/scripts/bootstrap-platform.sh"
    ).read_text(encoding="utf-8")
    assert "controller.tolerations[0].key=rudder.pool" in bootstrap
    assert "controller.tolerations[0].value=platform" in bootstrap
    assert "controller.tolerations[0].effect=NoSchedule" in bootstrap


def test_customer_workloads_share_the_platform_pool_until_quota_increases() -> None:
    """The 12-vCPU topology must be explicit in runtime and deployment config."""

    control_plane = (
        REPOSITORY_ROOT / "infra/kubernetes/platform/control-plane.yaml"
    ).read_text(encoding="utf-8")
    production_tfvars = (
        REPOSITORY_ROOT / "infra/gcp/terraform/envs/production.tfvars.example"
    ).read_text(encoding="utf-8")
    runtime_source = (
        REPOSITORY_ROOT / "control-plane/rudder_cp/runtime/kubernetes.py"
    ).read_text(encoding="utf-8")

    assert "name: RUDDER_KUBERNETES_WORKLOAD_POOL" in control_plane
    assert "value: platform" in control_plane
    assert "enable_workloads_pool = false" in production_tfvars
    assert "workload_node_selector" in runtime_source


def test_control_plane_manifest_uses_the_real_liveness_endpoint() -> None:
    """The production Deployment must probe FastAPI's actual health route."""

    control_plane = (
        REPOSITORY_ROOT / "infra/kubernetes/platform/control-plane.yaml"
    ).read_text(encoding="utf-8")

    assert control_plane.count("path: /healthz") == 2
    assert "path: /health\n" not in control_plane


def test_read_only_gke_verifier_checks_cluster_dns_before_rudder_platform() -> None:
    """A Ready node is not enough when system Pods are unschedulable."""

    verifier = (REPOSITORY_ROOT / "infra/gcp/scripts/verify-gke.sh").read_text(
        encoding="utf-8"
    )

    assert "kubectl -n kube-system rollout status deployment/kube-dns" in verifier
    assert "wait --for=condition=Ready pod -l k8s-app=kube-dns" in verifier
