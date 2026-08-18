"""Regression coverage for the GKE public-DNS platform contract.

These checks deliberately inspect the versioned infrastructure inputs rather
than a live cloud project.  They prevent a future chart or Terraform edit from
silently broadening the DNS identity or removing the required bootstrap step.
"""

from __future__ import annotations

from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_external_dns_uses_a_dedicated_workload_identity_principal() -> None:
    """ExternalDNS may discover zones but may administer only Rudder's zone."""

    identity = (REPOSITORY_ROOT / "infra/gcp/terraform/identity.tf").read_text()

    assert '"external_dns_dns_admin"' in identity
    assert 'role    = "roles/dns.admin"' in identity
    assert "subject/ns/external-dns/sa/external-dns" in identity
    assert "google_dns_managed_zone_iam_member" in identity
    assert '"external_dns_dns_reader"' in identity
    assert 'role    = "roles/dns.reader"' in identity
    assert "google_project_iam_member" in identity


def test_platform_bootstrap_installs_a_scoped_external_dns_controller() -> None:
    """DNS automation must be pinned, domain-scoped, and wait for readiness."""

    bootstrap = (REPOSITORY_ROOT / "infra/gcp/scripts/bootstrap-platform.sh").read_text()

    assert "EXTERNAL_DNS_CHART_VERSION" in bootstrap
    assert "helm repo add external-dns https://kubernetes-sigs.github.io/external-dns/" in bootstrap
    assert "external-dns/external-dns" in bootstrap
    assert '"$platform_dir/external-dns-values.yaml"' in bootstrap
    assert "external-dns/external-dns" in bootstrap

    values = (REPOSITORY_ROOT / "infra/kubernetes/platform/external-dns-values.yaml").read_text()
    assert "domainFilters" in values
    assert "labelFilter" in values
    assert "txtOwnerId" in values


def test_control_plane_ingress_is_marked_for_rudder_dns_automation() -> None:
    """ExternalDNS label filtering must include the stable control-plane route."""

    ingress = (REPOSITORY_ROOT / "infra/kubernetes/platform/control-plane-ingress.yaml").read_text()

    assert "app.kubernetes.io/managed-by: rudder" in ingress


def test_cluster_issuer_pins_dns01_to_rudder_child_zone() -> None:
    """ACME must write to Rudder's managed child zone, not its parent DNS zone."""

    bootstrap = (REPOSITORY_ROOT / "infra/gcp/scripts/bootstrap-platform.sh").read_text()
    issuer = (REPOSITORY_ROOT / "infra/kubernetes/platform/cluster-issuer.yaml").read_text()

    assert "RUDDER_GCP_DNS_ZONE" in bootstrap
    assert "hostedZoneName: ${RUDDER_GCP_DNS_ZONE}" in issuer
