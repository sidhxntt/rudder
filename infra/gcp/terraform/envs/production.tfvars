project_id   = "invytt-2483d"
region       = "asia-south1"
cluster_name = "rudder-gke"

# Keep disabled until the project-wide CPUS_ALL_REGIONS quota is raised. The
# regional CPUS quota is 32, but GKE currently enforces CPUS_ALL_REGIONS = 12,
# all of which is used by the existing regional system and platform pools.
enable_workloads_pool = false
