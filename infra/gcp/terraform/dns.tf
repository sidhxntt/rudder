resource "google_dns_managed_zone" "rudder" {
  name        = var.dns_zone_name
  dns_name    = var.dns_name
  description = "Delegated public DNS zone for Rudder application routes"

  dnssec_config {
    state = "on"
  }

  depends_on = [google_project_service.required]
}
