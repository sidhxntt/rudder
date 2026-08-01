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

# This identity is deliberately separate from the control-plane runtime. It
# owns the very small IAM policy surface needed to bind one generated CNPG
# Kubernetes ServiceAccount to the dedicated backup GSA.
resource "google_service_account" "backup_identity_broker" {
  account_id   = "rudder-backup-identity-broker"
  display_name = "Rudder per-environment backup identity broker"
}

resource "google_service_account" "cert_manager" {
  account_id   = "rudder-cert-manager"
  display_name = "Rudder cert-manager DNS challenge identity"
}

resource "google_service_account" "secret_sync" {
  account_id   = "rudder-secret-sync"
  display_name = "Rudder External Secrets runtime-sync identity"
}

# Terraform creates the Secret Manager container and the exact reader binding,
# but never a secret version. Operators add and rotate the JSON runtime values
# out of band; secret material therefore never enters Terraform state or Git.
resource "google_secret_manager_secret" "control_plane_runtime" {
  secret_id = "rudder-control-plane-runtime"

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

# ExternalDNS uses direct GKE Workload Identity federation rather than a
# Google service-account key or the node identity.  That keeps Cloud DNS write
# authority on one Kubernetes ServiceAccount only.
data "google_project" "current" {
  project_id = var.project_id
}

locals {
  external_dns_workload_identity = "principal://iam.googleapis.com/projects/${data.google_project.current.number}/locations/global/workloadIdentityPools/${var.project_id}.svc.id.goog/subject/ns/external-dns/sa/external-dns"
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

# The control plane starts a build but never receives Artifact Registry write
# access. Cloud Build runs as the narrower publisher identity below.
resource "google_project_iam_member" "runtime_cloud_build_editor" {
  project = var.project_id
  role    = "roles/cloudbuild.builds.editor"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_service_account_iam_member" "runtime_uses_build_identity" {
  service_account_id = google_service_account.build.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.runtime.email}"
}

# Google does not support attaching iam.serviceAccounts.setIamPolicy as a
# service-account-level role. A custom project role is therefore held only by
# the isolated broker identity. The broker's code fixes the target to the
# dedicated backup GSA and its private NetworkPolicy permits only the control
# plane to invoke it. No control-plane or node identity receives this role.
resource "google_project_iam_custom_role" "backup_identity_broker" {
  role_id     = "rudderBackupIdentityBroker"
  title       = "Rudder backup identity broker"
  description = "Get and update the dedicated CloudNativePG backup GSA IAM policy."
  permissions = [
    "iam.serviceAccounts.get",
    "iam.serviceAccounts.getIamPolicy",
    "iam.serviceAccounts.setIamPolicy",
  ]
}

resource "google_project_iam_member" "backup_identity_broker_policy_writer" {
  project = var.project_id
  role    = google_project_iam_custom_role.backup_identity_broker.name
  member  = "serviceAccount:${google_service_account.backup_identity_broker.email}"
}

resource "google_project_iam_member" "cert_manager_dns_admin" {
  project = var.project_id
  role    = "roles/dns.admin"
  member  = "serviceAccount:${google_service_account.cert_manager.email}"
}

resource "google_secret_manager_secret_iam_member" "control_plane_runtime_reader" {
  project   = var.project_id
  secret_id = google_secret_manager_secret.control_plane_runtime.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.secret_sync.email}"
}

# Scope the DNS writer to Rudder's delegated managed zone.  Do not give the
# ExternalDNS controller project-wide DNS permissions or node credentials.
resource "google_dns_managed_zone_iam_member" "external_dns_dns_admin" {
  project      = var.project_id
  managed_zone = google_dns_managed_zone.rudder.name
  role         = "roles/dns.admin"
  member       = local.external_dns_workload_identity
}

# ExternalDNS discovers the one managed zone it is allowed to update by listing
# the project's zones. Grant read-only discovery at project scope; mutation
# authority remains limited to google_dns_managed_zone.rudder above.
resource "google_project_iam_member" "external_dns_dns_reader" {
  project = var.project_id
  role    = "roles/dns.reader"
  member  = local.external_dns_workload_identity
}

resource "google_service_account_iam_member" "runtime_workload_identity" {
  service_account_id = google_service_account.runtime.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[rudder-system/rudder-control-plane]"

  depends_on = [google_container_cluster.rudder]
}

resource "google_service_account_iam_member" "backup_identity_broker_workload_identity" {
  service_account_id = google_service_account.backup_identity_broker.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[rudder-system/rudder-backup-identity-broker]"

  depends_on = [google_container_cluster.rudder]
}

resource "google_service_account_iam_member" "cert_manager_workload_identity" {
  service_account_id = google_service_account.cert_manager.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[cert-manager/cert-manager]"

  depends_on = [google_container_cluster.rudder]
}

resource "google_service_account_iam_member" "secret_sync_workload_identity" {
  service_account_id = google_service_account.secret_sync.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "serviceAccount:${var.project_id}.svc.id.goog[rudder-system/rudder-secret-sync]"

  depends_on = [google_container_cluster.rudder]
}
