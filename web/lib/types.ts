/**
 * Wire types for the Rudder control plane.
 *
 * These mirror `docs/PRD.md` → "Data Model" plus the Phase 1 "Schema deltas"
 * (`Service.container_port`, `Deployment.error_message`, `Instance.stopped_at`,
 * the `Domain` table). They are the *API projection* of those tables, which is
 * why `Variable` has no value field: the PRD states the table carries
 * `value_encrypted` and "the API must never return it". Phase 1 step 4 repeats
 * it — "Variable responses never include the decrypted value. Write-only field."
 *
 * When the OpenAPI-generated client lands, this file is replaced wholesale by
 * generated definitions and `lib/api.ts` re-exports from there.
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
  | "stopped";

export type DomainTargetType = "service" | "deployment";

export interface Project {
  id: string;
  name: string;
  owner_id: string;
  created_at: string;
}

export interface Environment {
  id: string;
  project_id: string;
  name: string;
  is_production: boolean;
  wg_subnet: string | null;
}

export interface Service {
  id: string;
  environment_id: string;
  name: string;
  kind: ServiceKind;
  source_repo: string | null;
  source_branch: string | null;
  dockerfile_path: string | null;
  build_config: Record<string, unknown> | null;
  start_command: string | null;
  health_check_path: string | null;
  health_check_port: number | null;
  container_port: number;
  cpu_limit: number;
  memory_limit_mb: number;
  replica_count: number;
  canvas_x: number;
  canvas_y: number;
}

/** Body of `PATCH /services/{id}`. Canvas drag persists layout only (D6). */
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
}

export interface Deployment {
  id: string;
  service_id: string;
  image_tag: string;
  commit_sha: string;
  status: DeploymentStatus;
  build_log_url: string | null;
  error_message: string | null;
  created_at: string;
  became_live_at: string | null;
}

export interface Instance {
  id: string;
  deployment_id: string;
  node_id: string;
  container_id: string | null;
  status: InstanceStatus;
  wg_ip: string | null;
  started_at: string | null;
  stopped_at: string | null;
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
}

/**
 * Phase 1 streams build logs over SSE (`docs/phases/PHASE-1-single-host.md`
 * step 5). Until the endpoint exists the UI polls a snapshot; `complete` is
 * what lets it stop polling.
 */
export interface BuildLog {
  deployment_id: string;
  lines: string[];
  complete: boolean;
}

/** Derived, not stored. `Service` has no status column in the PRD data model. */
export type ServiceStatus = "live" | "building" | "failed" | "draining" | "unknown";
