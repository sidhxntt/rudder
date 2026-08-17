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

output "build_source_bucket" {
  value = google_storage_bucket.build_sources.name
}

output "build_logs_bucket" {
  value = google_storage_bucket.build_logs.name
}

output "build_service_account" {
  value = google_service_account.build.email
}

output "workload_identity_pool" {
  value = "${var.project_id}.svc.id.goog"
}

output "dns_name_servers" {
  value = google_dns_managed_zone.rudder.name_servers
}

output "control_plane_runtime_secret_name" {
  value = google_secret_manager_secret.control_plane_runtime.secret_id
}

output "secret_sync_service_account" {
  value = google_service_account.secret_sync.email
}
