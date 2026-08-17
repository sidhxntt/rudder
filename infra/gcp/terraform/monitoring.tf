# Cloud Monitoring is the durable alert evaluator for the GKE runtime.  Policies
# deliberately live beside the cluster IaC, rather than in a manually edited
# console configuration.  Notification channels are injected by operators so
# recipient addresses and integration tokens never enter this repository.

resource "google_monitoring_alert_policy" "gke_container_restarts" {
  project               = var.project_id
  display_name          = "Rudder GKE container restarts"
  combiner              = "OR"
  notification_channels = var.alert_notification_channels

  documentation {
    mime_type = "text/markdown"
    content   = <<-EOT
      A GKE container restarted in the Rudder cluster. Inspect the Pod events,
      immutable deployment record, image digest, readiness state, and the
      Phase 4 GKE operations runbook before retrying or rolling back.
    EOT
  }

  conditions {
    display_name = "Container restart count increases"

    condition_threshold {
      filter          = "metric.type=\"kubernetes.io/container/restart_count\" AND resource.type=\"k8s_container\" AND resource.labels.cluster_name=\"${var.cluster_name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_DELTA"
      }

      trigger {
        count = 1
      }
    }
  }

  alert_strategy {
    auto_close = "604800s"
  }
}

# Image pull and similar Kubernetes scheduling failures are emitted as Events
# before a candidate can be promoted.  A matched-log alert gives on-call a
# direct path from the incident to the exact namespace and Pod involved.
resource "google_monitoring_alert_policy" "gke_candidate_image_pull_failure" {
  project               = var.project_id
  display_name          = "Rudder GKE candidate image pull failure"
  combiner              = "OR"
  notification_channels = var.alert_notification_channels

  documentation {
    mime_type = "text/markdown"
    content   = <<-EOT
      A candidate Pod could not pull its image. Verify the immutable Artifact
      Registry digest and runtime identity. Do not repoint the live route;
      Rudder removes failed candidates before promotion.
    EOT
  }

  conditions {
    display_name = "Kubernetes image-pull failure event"

    condition_matched_log {
      filter = "resource.type=\"k8s_pod\" AND log_id(\"events\") AND jsonPayload.reason=\"Failed\" AND jsonPayload.message=~\"(?i)(ErrImagePull|ImagePullBackOff|pull image)\""
    }
  }

  alert_strategy {
    auto_close = "604800s"

    notification_rate_limit {
      period = "300s"
    }
  }
}
