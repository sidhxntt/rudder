/**
 * Wire types for the Rudder control plane.
 *
 * These are transcribed from the live OpenAPI document (`GET /openapi.json`),
 * schema by schema — not from the PRD data model, which is the *table* shape.
 * Where the two differ the API wins, because that is what arrives over the
 * wire. The differences that matter:
 *
 *   - `Deployment` has no `build_log_url`. The build log is a sub-resource at
 *     `GET /deployments/{id}/build-log` and it is an SSE stream, not a document.
 *   - `Deployment.image_tag` and `.commit_sha` are nullable: a deploy that dies
 *     before the clone resolves never gets either.
 *   - `Instance` carries no `wg_ip` in Phase 1 (there is no mesh yet).
 *   - `Service.build_config`, `.source_branch` and `.health_check_path` are
 *     non-null; `.source_repo` and `.start_command` are nullable.
 *   - `Variable` has no value field, by design. The control plane stores
 *     `value_encrypted` and no endpoint ever returns it.
 */

export type ServiceKind = "app" | "database" | "static";

export type DeploymentStatus =
  | "queued"
  | "building"
  | "deploying"
  | "live"
  | "failed"
  | "superseded";

export type InstanceStatus =
  | "starting"
  | "healthy"
  | "unhealthy"
  | "draining"
  | "stopped"
  | "unreachable";

export type NodeStatus =
  | "healthy"
  | "unreachable"
  | "draining";

export type DomainTargetType = "service" | "deployment";

/** `GET /auth/me` → UserRead. */
export interface User {
  id: string;
  email: string;
  created_at: string;
}

/** `POST /auth/token` → TokenResponse. The token itself is deliberately unused
 *  in the browser: the same response sets an httpOnly `rudder_token` cookie and
 *  that is the only credential this app ever holds. */
export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface Project {
  id: string;
  name: string;
  owner_id: string;
  created_at: string;
}

/** `GET /nodes` → NodeReadWithInstances. */
export interface Node {
  id: string;
  hostname: string;
  ip_address: string;
  status: NodeStatus;
  cpu_total: number;
  memory_total_mb: number;
  cpu_allocated: number;
  memory_allocated_mb: number;
  last_heartbeat_at: string | null;
  created_at: string;
  reported_state: Record<string, unknown> | null;
  instances: Instance[];
}

export interface Environment {
  id: string;
  project_id: string;
  name: string;
  is_production: boolean;
  github_pr_number: number | null;
  /** Optional in the schema, not merely nullable — it can be absent entirely. */
  wg_subnet?: string | null;
  created_at: string;
}

export interface Service {
  id: string;
  environment_id: string;
  name: string;
  kind: ServiceKind;
  source_repo: string | null;
  source_branch: string;
  dockerfile_path: string | null;
  build_config: Record<string, unknown>;
  start_command: string | null;
  container_port: number;
  health_check_path: string;
  health_check_port: number | null;
  cpu_limit: number;
  memory_limit_mb: number;
  replica_count: number;
  canvas_x: number;
  canvas_y: number;
  created_at: string;
}

/**
 * Body of `PATCH /services/{id}`.
 *
 * The API's own ServiceUpdate accepts every mutable column; this narrows it to
 * the two the canvas is allowed to touch. D6: layout is UI metadata, so the
 * only thing a drag may ever send is a position.
 */
export interface ServiceUpdate {
  canvas_x?: number;
  canvas_y?: number;
}

/** No value. Ever. See the note at the top of this file. */
export interface Variable {
  id: string;
  service_id: string;
  key: string;
  is_reference: boolean;
  created_at: string;
}

export interface Deployment {
  id: string;
  service_id: string;
  status: DeploymentStatus;
  image_tag: string | null;
  commit_sha: string | null;
  error_message: string | null;
  created_at: string;
  became_live_at: string | null;
}

export interface Instance {
  id: string;
  deployment_id: string;
  node_id: string;
  status: InstanceStatus;
  container_id: string | null;
  started_at: string | null;
  stopped_at: string | null;
}

export interface RuntimeMetric {
  captured_at: string;
  cpu_percent: number;
  memory_bytes: number;
  resolution_seconds: number;
}

export interface Domain {
  id: string;
  hostname: string;
  environment_id: string;
  target_type: DomainTargetType;
  service_id: string | null;
  deployment_id: string | null;
  is_system: boolean;
  tls_enabled: boolean;
  created_at: string;
}

export interface GitHubImportStatus {
  configured: boolean;
  install_url: string | null;
  message: string;
}

export interface GitHubRepository {
  full_name: string;
  default_branch: string;
  private: boolean;
}

export interface GitHubInstallation {
  id: number;
  account_login: string;
  repository_selection: string;
}

export interface StarterTemplate {
  id: string;
  name: string;
  description: string;
  addons: string[];
}

export interface GitHubImportPreview {
  is_node_app: boolean;
  addons: string[];
  externally_managed: string[];
  compose_source: "repository" | "generated";
  compose_manifest: string;
  services: Array<{
    name: string;
    public_port: number | null;
    container_port: number | null;
    role: string;
    is_public: boolean;
  }>;
  processes: Array<{
    role: "web" | "worker" | "scheduler" | "realtime";
    command: string;
    source: "procfile" | "package_json";
  }>;
}

export interface GitHubImportConfirmation {
  import_id: string;
  project_id: string;
  environment_id: string;
  app_service_id: string;
}

export interface GitHubImportStep {
  label: string;
  service_id: string;
  service_name: string | null;
  deployment_id: string | null;
  status: DeploymentStatus;
  error_message: string | null;
}

export interface GitHubImport extends GitHubImportConfirmation {
  repository: string;
  branch: string;
  steps: GitHubImportStep[];
}

/** Payload of the terminal `event: end` frame on the build-log stream. */
export type BuildOutcome = "succeeded" | "failed";

/** Derived, not stored. `Service` has no status column in the PRD data model. */
export type ServiceStatus = "live" | "building" | "failed" | "draining" | "unknown";

/** Durable Kubernetes operations intent and its latest observed result. */
export type OperationStatus =
  | "pending"
  | "progressing"
  | "healthy"
  | "degraded"
  | "failed"
  | "cancelled";

export type OperationKind =
  | "configure"
  | "scale"
  | "resources"
  | "autoscaling"
  | "placement"
  | "rollout"
  | "rollback"
  | "backup"
  | "restore"
  | "read_replica"
  | "storage"
  | "schedule"
  | "job"
  | "observability";

export interface ServiceOperation {
  id: string;
  service_id: string;
  kind: OperationKind;
  status: OperationStatus;
  requested: Record<string, unknown>;
  observed: Record<string, unknown>;
  error_message: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface ServiceOperationsEnvelope {
  desired: Record<string, unknown>;
  observed: Record<string, unknown>;
  version: number;
  pending_reconciliation: boolean;
  updated_at: string;
  history: ServiceOperation[];
  /** Safe server-authored flags; command arguments and secrets are never exposed. */
  capabilities: ServiceOperationCapabilities;
  /** HTTP ETag used for safe compare-and-swap configuration patches. */
  etag: string | null;
}

export interface ServiceOperationCapabilities {
  database_engine: string | null;
  data_role: string | null;
  job_commands_available: boolean;
  /** Only true when the control plane can expand this service's PVC safely. */
  storage_expansion_available?: boolean;
  /** Legacy combined flag. New clients must check each data action separately. */
  backup_restore_available?: boolean;
  /** Only true when Rudder has a configured physical backup destination. */
  backup_available?: boolean;
  /** Only true when Rudder supports a safe recovery-cluster cutover. */
  restore_available?: boolean;
  /** Only true when the configured primary supports managed SQL replicas. */
  read_replicas_available?: boolean;
}

export interface ServiceOperationsState {
  desired: Record<string, unknown>;
  observed: Record<string, unknown>;
  version: number;
  pending_reconciliation: boolean;
  updated_at: string;
  etag: string | null;
}

export interface ResourceOperationRequest {
  cpu_request?: string;
  cpu_limit?: string;
  memory_request_mb?: number;
  memory_limit_mb?: number;
}

export interface AutoscalingOperationRequest {
  min_replicas: number;
  max_replicas: number;
  target_cpu_percent?: number;
  target_memory_percent?: number;
}
