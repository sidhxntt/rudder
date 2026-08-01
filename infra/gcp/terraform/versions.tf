terraform {
  required_version = ">= 1.8.0"

  # Initialise with the versioned GCS backend created by
  # ../scripts/bootstrap-state.sh. Keeping the backend configuration out of
  # this file allows a fresh project to bootstrap that bucket safely.
  backend "gcs" {}

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 7.0"
    }
  }
}
