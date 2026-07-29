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

resource "google_storage_bucket_iam_member" "backup_object_creator" {
  bucket = google_storage_bucket.backups.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${google_service_account.backup.email}"
}

resource "google_storage_bucket_iam_member" "backup_object_viewer" {
  bucket = google_storage_bucket.backups.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.backup.email}"
}
