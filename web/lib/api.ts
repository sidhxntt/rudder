/**
 * THE SEAM.
 *
 * Every byte of data the UI touches passes through this module. Nothing else in
 * `web/` imports `lib/mock.ts`, and nothing else in `web/` calls `fetch`.
 *
 * `docs/PRD.md` → "Repo structure" already names this file "generated TS
 * client". Today each function delegates to the in-memory mock because the
 * control plane does not exist yet (Phase 1 steps 2-9). When the OpenAPI client
 * is generated, every body below is replaced with one client call and the
 * signatures do not move. The REST shape each function stands for is written
 * above it so the swap is mechanical.
 */

import * as mock from "./mock";
import type {
  BuildLog,
  Deployment,
  Domain,
  Environment,
  Instance,
  Project,
  Service,
  ServiceUpdate,
  Variable,
} from "./types";

/** GET /projects */
export function listProjects(): Promise<Project[]> {
  return mock.listProjects();
}

/** GET /projects/{project_id}/environments */
export function listEnvironments(projectId: string): Promise<Environment[]> {
  return mock.listEnvironments(projectId);
}

/** GET /environments/{environment_id}/services */
export function listServices(environmentId: string): Promise<Service[]> {
  return mock.listServices(environmentId);
}

/** GET /services/{service_id} */
export function getService(serviceId: string): Promise<Service> {
  return mock.getService(serviceId);
}

/**
 * PATCH /services/{service_id}
 *
 * Canvas drag persists `canvas_x`/`canvas_y` through here. Per D6 this is UI
 * metadata: the control plane stores it, nothing reconciles against it.
 */
export function updateService(serviceId: string, patch: ServiceUpdate): Promise<Service> {
  return mock.updateService(serviceId, patch);
}

/** GET /environments/{environment_id}/domains */
export function listDomains(environmentId: string): Promise<Domain[]> {
  return mock.listDomains(environmentId);
}

/** GET /services/{service_id}/deployments — newest first */
export function listDeployments(serviceId: string): Promise<Deployment[]> {
  return mock.listDeployments(serviceId);
}

/** GET /services/{service_id}/instances */
export function listInstances(serviceId: string): Promise<Instance[]> {
  return mock.listInstances(serviceId);
}

/** POST /services/{service_id}/deploy → 202, Deployment(status=queued) */
export function createDeployment(serviceId: string): Promise<Deployment> {
  return mock.createDeployment(serviceId);
}

/**
 * GET /deployments/{deployment_id}/logs
 *
 * Phase 1 step 5 exposes build logs over SSE. Until that endpoint exists this
 * returns a snapshot and the caller polls while `complete` is false; the
 * replacement is an EventSource subscription behind the same call site.
 */
export function getBuildLog(deploymentId: string): Promise<BuildLog> {
  return mock.getBuildLog(deploymentId);
}

/** GET /services/{service_id}/variables — values are never in the response */
export function listVariables(serviceId: string): Promise<Variable[]> {
  return mock.listVariables(serviceId);
}

/** PUT /services/{service_id}/variables/{key} — idempotent, value write-only */
export function putVariable(serviceId: string, key: string, value: string): Promise<Variable> {
  return mock.putVariable(serviceId, key, value);
}

/** DELETE /services/{service_id}/variables/{key} */
export function deleteVariable(serviceId: string, key: string): Promise<void> {
  return mock.deleteVariable(serviceId, key);
}
