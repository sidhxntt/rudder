variable "project_id" {
  description = "Google Cloud project that owns the shared Rudder platform."
  type        = string
}

variable "region" {
  description = "Regional GKE location."
  type        = string
  default     = "asia-south1"
}

variable "cluster_name" {
  description = "Name of the shared, attach-mode Rudder GKE cluster."
  type        = string
  default     = "rudder-gke"
}

variable "network_name" {
  description = "Dedicated VPC for GKE. It must not reuse the Phase 2 VM lab VPC."
  type        = string
  default     = "rudder-gke-vpc"
}

variable "subnet_cidr" {
  description = "Primary subnet range for GKE nodes."
  type        = string
  default     = "10.80.0.0/20"
}

variable "pods_cidr" {
  description = "Secondary range allocated to Pods."
  type        = string
  default     = "10.96.0.0/14"
}

variable "services_cidr" {
  description = "Secondary range allocated to Kubernetes Services."
  type        = string
  default     = "10.112.0.0/20"
}

variable "master_ipv4_cidr_block" {
  description = "Private control-plane range. It must not overlap any VPC range."
  type        = string
  default     = "172.20.0.0/28"
}

variable "operator_authorized_cidrs" {
  description = "CIDRs allowed to reach the public GKE control-plane endpoint during bootstrap."
  type = list(object({
    cidr_block   = string
    display_name = string
  }))

  validation {
    condition     = length(var.operator_authorized_cidrs) > 0
    error_message = "At least one explicitly reviewed operator CIDR is required; do not expose the GKE API to all addresses."
  }
}

variable "node_machine_type" {
  description = "Machine type used by the initial bounded node pools."
  type        = string
  default     = "e2-standard-2"
}

variable "dns_zone_name" {
  description = "Cloud DNS managed-zone resource name."
  type        = string
  default     = "rudder-subdomain"
}

variable "dns_name" {
  description = "Rudder delegated domain, with a trailing dot."
  type        = string
  default     = "rudder.invytt.com."

  validation {
    condition     = can(regex("^[a-z0-9.-]+\\.$", var.dns_name))
    error_message = "dns_name must be a lowercase fully-qualified DNS name ending in a dot."
  }
}

variable "backup_retention_days" {
  description = "Days to retain noncurrent backup objects before lifecycle deletion."
  type        = number
  default     = 35

  validation {
    condition     = var.backup_retention_days >= 7
    error_message = "Backup retention must be at least seven days."
  }
}
