resource "google_container_cluster" "rudder" {
  name     = var.cluster_name
  location = var.region

  network    = google_compute_network.rudder.id
  subnetwork = google_compute_subnetwork.gke.id

  networking_mode     = "VPC_NATIVE"
  deletion_protection = true

  # The cluster is bootstrapped through gcloud, then imported into this state.
  # Its temporary default pool is removed only after the system pool exists,
  # avoiding an empty regional control plane during the handoff.

  # These are cluster updates rather than prerequisites. Enabling them after
  # the API accepts the base private cluster keeps the bootstrap request
  # portable across supported GKE control-plane versions.
  # enable_l4_ilb_subsetting    = true
  # enable_intranode_visibility = true

  ip_allocation_policy {
    cluster_secondary_range_name  = "pods"
    services_secondary_range_name = "services"
  }

  # Rudder's per-environment NetworkPolicy is a security boundary, not merely
  # Kubernetes metadata. Keep both the GKE add-on and node enforcement enabled
  # so the policy rendered for each tenant namespace is actually enforced.
  addons_config {
    network_policy_config {
      disabled = false
    }
  }

  network_policy {
    enabled  = true
    provider = "CALICO"
  }

  private_cluster_config {
    # Modern GKE provides an internal control-plane endpoint in the chosen
    # subnet automatically. Do not combine the legacy master CIDR/subnetwork
    # fields with the current endpoint API; that request is rejected by GKE.
    enable_private_nodes    = true
    enable_private_endpoint = false
  }

  # Operator access uses the GKE DNS endpoint and Google IAM credentials.
  # This leaves the workload nodes private and does not enable client
  # certificates, Kubernetes service-account tokens, or anonymous access.
  control_plane_endpoints_config {
    dns_endpoint_config {
      allow_external_traffic    = true
      enable_k8s_certs_via_dns  = false
      enable_k8s_tokens_via_dns = false
    }
  }

  # Endpoint hardening is applied after cluster creation. Combining the current
  # control-plane endpoint API with a private-node regional create request is
  # rejected by the GKE API in this project. The baseline still creates private
  # nodes; a post-bootstrap update switches operator access to the DNS/IAM
  # endpoint without weakening workload isolation.

  workload_identity_config {
    workload_pool = "${var.project_id}.svc.id.goog"
  }

  release_channel {
    channel = "REGULAR"
  }

  logging_config {
    enable_components = ["SYSTEM_COMPONENTS", "WORKLOADS"]
  }

  depends_on = [
    google_project_service.required,
    google_project_iam_member.node_registry_reader,
  ]
}

resource "google_container_node_pool" "system" {
  name       = "system"
  location   = var.region
  cluster    = google_container_cluster.rudder.name
  node_count = 1

  autoscaling {
    min_node_count = 1
    max_node_count = 3
  }

  node_config {
    machine_type    = var.node_machine_type
    service_account = google_service_account.nodes.email
    # GKE adds userinfo.email to the default cloud-platform scope on the
    # bootstrapped pool. Keep Terraform aligned with that live baseline so
    # importing the pool never proposes a replacement.
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform",
      "https://www.googleapis.com/auth/userinfo.email",
    ]
    disk_size_gb = 25
    # This pool intentionally stays untainted: CoreDNS and other GKE-managed
    # components do not carry Rudder-specific tolerations. Platform services
    # are instead isolated on the tainted platform pool below.
    labels = { "rudder.pool" = "system" }
    workload_metadata_config { mode = "GKE_METADATA" }
    shielded_instance_config {
      # Secure Boot needs a deliberate rolling node-pool migration after the
      # production baseline is live; enabling it in-place would replace every
      # regional node in this imported pool.
      enable_secure_boot          = false
      enable_integrity_monitoring = true
    }
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }
}

resource "google_container_node_pool" "platform" {
  name       = "platform"
  location   = var.region
  cluster    = google_container_cluster.rudder.name
  node_count = 1

  autoscaling {
    min_node_count = 1
    max_node_count = 3
  }

  node_config {
    machine_type    = var.node_machine_type
    service_account = google_service_account.nodes.email
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform",
      "https://www.googleapis.com/auth/userinfo.email",
    ]
    disk_size_gb = 25
    labels       = { "rudder.pool" = "platform" }
    taint {
      key    = "rudder.pool"
      value  = "platform"
      effect = "NO_SCHEDULE"
    }
    workload_metadata_config { mode = "GKE_METADATA" }
    shielded_instance_config {
      enable_secure_boot          = false
      enable_integrity_monitoring = true
    }
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }
}

resource "google_container_node_pool" "workloads" {
  # A regional e2-standard-2 pool requires six vCPUs. GKE validates the
  # project-wide CPUS_ALL_REGIONS quota, which currently admits only the
  # system and platform pools (12 vCPUs total).
  # Keep this desired pool explicit, but do not ask Terraform to create it
  # until the target region's CPUS quota admits at least 18 vCPUs.
  count = var.enable_workloads_pool ? 1 : 0

  name       = "workloads"
  location   = var.region
  cluster    = google_container_cluster.rudder.name
  node_count = 1

  autoscaling {
    min_node_count = 1
    max_node_count = 5
  }

  node_config {
    machine_type    = var.node_machine_type
    service_account = google_service_account.nodes.email
    oauth_scopes = [
      "https://www.googleapis.com/auth/cloud-platform",
      "https://www.googleapis.com/auth/userinfo.email",
    ]
    disk_size_gb = 25
    labels       = { "rudder.pool" = "workloads" }
    workload_metadata_config { mode = "GKE_METADATA" }
    shielded_instance_config {
      enable_secure_boot          = false
      enable_integrity_monitoring = true
    }
  }

  management {
    auto_repair  = true
    auto_upgrade = true
  }
}
