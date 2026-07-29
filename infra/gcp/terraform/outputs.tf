output "cluster_name" {
  value = google_container_cluster.rudder.name
}

output "cluster_region" {
  value = google_container_cluster.rudder.location
}

output "cluster_endpoint" {
  value     = google_container_cluster.rudder.endpoint
  sensitive = true
}

output "artifact_registry" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.rudder.repository_id}"
}

output "backup_bucket" {
  value = google_storage_bucket.backups.name
}

output "workload_identity_pool" {
  value = "${var.project_id}.svc.id.goog"
}

output "dns_name_servers" {
  value = google_dns_managed_zone.rudder.name_servers
}
