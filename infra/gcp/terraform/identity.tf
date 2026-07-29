resource "google_service_account" "nodes" {
  account_id   = "rudder-gke-nodes"
  display_name = "Rudder GKE node identity"
}

resource "google_service_account" "build" {
  account_id   = "rudder-build"
  display_name = "Rudder immutable image publisher"
}

resource "google_service_account" "runtime" {
  account_id   = "rudder-runtime"
  display_name = "Rudder control-plane workload identity"
}

resource "google_service_account" "backup" {
  account_id   = "rudder-backup"
  display_name = "Rudder CloudNativePG backup identity"
}

resource "google_service_account" "cert_manager" {
  account_id   = "rudder-cert-manager"
  display_name = "Rudder cert-manager DNS challenge identity"
}

resource "google_project_iam_member" "node_registry_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.nodes.email}"
}

resource "google_project_iam_member" "build_registry_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.build.email}"
}

resource "google_project_iam_member" "runtime_registry_reader" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "cert_manager_dns_admin" {
  project = var.project_id
  role    = "roles/dns.admin"
  member  = "serviceAccount:${google_service_account.cert_manager.email}"
}

resource "google_service_account_iam_member" "runtime_workload_identity" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[rudder-system/rudder-control-plane]"
}

resource "google_service_account_iam_member" "backup_workload_identity" {
  service_account_id = google_service_account.backup.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[rudder-system/rudder-cnpg-backup]"
}

resource "google_service_account_iam_member" "cert_manager_workload_identity" {
  service_account_id = google_service_account.cert_manager.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[cert-manager/cert-manager]"
}
