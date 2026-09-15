from pathlib import Path


def test_kind_control_plane_allows_cnpg_to_reach_the_kubernetes_api_service() -> None:
    root = Path(__file__).resolve().parents[2]
    manifest = (root / "docker-compose.kind.yml").read_text()
    makefile = (root / "Makefile").read_text()

    assert (
        "RUDDER_KUBERNETES_API_SERVER_ENDPOINT_CIDR: "
        "${RUDDER_KUBERNETES_API_SERVER_ENDPOINT_CIDR:-}"
    ) in manifest
    assert (
        "RUDDER_KUBERNETES_API_SERVER_ENDPOINT_PORT: "
        "${RUDDER_KUBERNETES_API_SERVER_ENDPOINT_PORT:-443}"
    ) in manifest
    assert "kubectl -n default get endpoints kubernetes" in makefile
    assert 'RUDDER_KUBERNETES_API_SERVER_ENDPOINT_CIDR="$$api_server_endpoint/32"' in makefile
    assert 'RUDDER_KUBERNETES_API_SERVER_ENDPOINT_PORT="$$api_server_endpoint_port"' in makefile


def test_kind_bootstrap_installs_and_waits_for_metrics_server() -> None:
    root = Path(__file__).resolve().parents[2]
    bootstrap = (root / "infra/kind/bootstrap.sh").read_text()

    assert "metrics-server/releases/download/v0.7.2/components.yaml" in bootstrap
    assert "deployment/metrics-server" in bootstrap
    assert "v1beta1.metrics.k8s.io" in bootstrap
    assert "patch deployment metrics-server --type='strategic'" in bootstrap
