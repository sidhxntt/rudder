resource "google_storage_bucket" "backups" {
  name                        = "${var.project_id}-rudder-backups"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  lifecycle_rule {
    action { type = "Delete" }
    condition {
      age            = var.backup_retention_days
      with_state     = "ARCHIVED"
      matches_prefix = ["cnpg/"]
    }
  }
}

# Cloud Build receives an archive of an already-authorized Git revision.  This
# bucket is deliberately separate from database backups and objects expire
# quickly after the build path deletes them.
resource "google_storage_bucket" "build_sources" {
  name                        = "${var.project_id}-rudder-build-source"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  lifecycle_rule {
    action { type = "Delete" }
    condition { age = 2 }
  }
}

# Cloud Build writes the detailed build output here.  Keeping this separate
# from runtime logs gives the control plane a durable, replica-independent
# source for the UI build-log view.
resource "google_storage_bucket" "build_logs" {
  name                        = "${var.project_id}-rudder-build-logs"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  lifecycle_rule {
    action { type = "Delete" }
    condition { age = 30 }
  }
}

resource "google_storage_bucket_iam_member" "backup_object_admin" {
  bucket = google_storage_bucket.backups.name
  # CNPG/Barman creates, lists, replaces and prunes backup metadata and WAL
  # objects. This role is limited to object operations on this one bucket.
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.backup.email}"
}

resource "google_storage_bucket_iam_member" "runtime_build_source_writer" {
  bucket = google_storage_bucket.build_sources.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_storage_bucket_iam_member" "build_source_reader" {
  bucket = google_storage_bucket.build_sources.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.build.email}"
}

resource "google_storage_bucket_iam_member" "build_logs_writer" {
  bucket = google_storage_bucket.build_logs.name
  # Cloud Build validates a user-created log bucket before starting a build,
  # which requires both bucket metadata and object write/delete permissions.
  # Keep this elevated predefined role constrained to the one private bucket.
  role   = "roles/storage.admin"
  member = "serviceAccount:${google_service_account.build.email}"
}

resource "google_storage_bucket_iam_member" "runtime_build_logs_reader" {
  bucket = google_storage_bucket.build_logs.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.runtime.email}"
}
