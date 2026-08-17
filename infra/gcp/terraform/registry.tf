resource "google_artifact_registry_repository" "rudder" {
  location      = var.region
  repository_id = "rudder"
  description   = "Immutable Rudder platform and customer workload images"
  format        = "DOCKER"

  depends_on = [google_project_service.required]
}
