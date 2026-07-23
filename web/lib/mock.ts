/**
 * Mock control plane. The backend does not exist yet (Phase 1 steps 2-9 are in
 * flight); this module stands in for it so the canvas can be built against the
 * real data shapes.
 *
 * Rules this file obeys, because the real API will:
 *   - a Variable never carries a value out of here (write-only field)
 *   - a Deployment is immutable once terminal; deploying supersedes, never edits
 *   - Service has no status column — status is derived from Deployment+Instance
 *
 * Nothing outside `lib/api.ts` may import this module.
 */

import type {
  BuildLog,
  Deployment,
  DeploymentStatus,
  Domain,
  Environment,
  Instance,
  Project,
  Service,
  ServiceUpdate,
  Variable,
} from "./types";

const T0 = Date.now();
const min = 60_000;
const iso = (ms: number): string => new Date(ms).toISOString();

let seq = 0;
const nextId = (prefix: string): string => `${prefix}_${(++seq).toString(36)}${Date.now().toString(36)}`;

// --- Seed -----------------------------------------------------------------

const projects: Project[] = [
  { id: "prj_shop", name: "shop", owner_id: "usr_root", created_at: iso(T0 - 90 * 24 * 60 * min) },
  { id: "prj_atlas", name: "atlas", owner_id: "usr_root", created_at: iso(T0 - 12 * 24 * 60 * min) },
];

const environments: Environment[] = [
  { id: "env_shop_prod", project_id: "prj_shop", name: "production", is_production: true, wg_subnet: "10.42.0.0/24" },
  { id: "env_shop_stg", project_id: "prj_shop", name: "staging", is_production: false, wg_subnet: "10.42.1.0/24" },
  { id: "env_atlas_prod", project_id: "prj_atlas", name: "production", is_production: true, wg_subnet: "10.43.0.0/24" },
];

const services: Service[] = [
  {
    id: "svc_api",
    environment_id: "env_shop_prod",
    name: "api",
    kind: "app",
    source_repo: "rudderlabs/shop-api",
    source_branch: "main",
    dockerfile_path: null,
    build_config: { builder: "buildkit", template: "node" },
    start_command: "node dist/server.js",
    health_check_path: "/healthz",
    health_check_port: 3000,
    container_port: 3000,
    cpu_limit: 1,
    memory_limit_mb: 512,
    replica_count: 1,
    canvas_x: 120,
    canvas_y: 96,
  },
  {
    id: "svc_worker",
    environment_id: "env_shop_prod",
    name: "worker",
    kind: "app",
    source_repo: "rudderlabs/shop-api",
    source_branch: "main",
    dockerfile_path: null,
    build_config: { builder: "buildkit", template: "node" },
    start_command: "node dist/worker.js",
    health_check_path: "/healthz",
    health_check_port: 3001,
    container_port: 3001,
    cpu_limit: 0.5,
    memory_limit_mb: 256,
    replica_count: 1,
    canvas_x: 120,
    canvas_y: 300,
  },
  {
    id: "svc_postgres",
    environment_id: "env_shop_prod",
    name: "postgres",
    kind: "database",
    source_repo: null,
    source_branch: null,
    dockerfile_path: null,
    build_config: null,
    start_command: null,
    health_check_path: null,
    health_check_port: null,
    container_port: 5432,
    cpu_limit: 1,
    memory_limit_mb: 1024,
    replica_count: 1,
    canvas_x: 480,
    canvas_y: 198,
  },
  {
    id: "svc_web",
    environment_id: "env_shop_prod",
    name: "web",
    kind: "static",
    source_repo: "rudderlabs/shop-web",
    source_branch: "main",
    dockerfile_path: null,
    build_config: { builder: "buildkit", template: "static-nginx" },
    start_command: null,
    health_check_path: "/",
    health_check_port: 80,
    container_port: 80,
    cpu_limit: 0.25,
    memory_limit_mb: 128,
    replica_count: 1,
    canvas_x: 480,
    canvas_y: 396,
  },
  {
    id: "svc_api_stg",
    environment_id: "env_shop_stg",
    name: "api",
    kind: "app",
    source_repo: "rudderlabs/shop-api",
    source_branch: "feat-auth",
    dockerfile_path: null,
    build_config: { builder: "buildkit", template: "node" },
    start_command: "node dist/server.js",
    health_check_path: "/healthz",
    health_check_port: 3000,
    container_port: 3000,
    cpu_limit: 0.5,
    memory_limit_mb: 512,
    replica_count: 1,
    canvas_x: 160,
    canvas_y: 140,
  },
  {
    id: "svc_atlas_api",
    environment_id: "env_atlas_prod",
    name: "atlas-api",
    kind: "app",
    source_repo: "rudderlabs/atlas",
    source_branch: "main",
    dockerfile_path: "Dockerfile",
    build_config: null,
    start_command: null,
    health_check_path: "/health",
    health_check_port: 8080,
    container_port: 8080,
    cpu_limit: 1,
    memory_limit_mb: 512,
    replica_count: 1,
    canvas_x: 200,
    canvas_y: 160,
  },
];

const domains: Domain[] = [
  {
    id: "dom_api",
    hostname: "api.production.localhost",
    environment_id: "env_shop_prod",
    target_type: "service",
    service_id: "svc_api",
    deployment_id: null,
    is_system: true,
    tls_enabled: false,
  },
  {
    id: "dom_web",
    hostname: "web.production.localhost",
    environment_id: "env_shop_prod",
    target_type: "service",
    service_id: "svc_web",
    deployment_id: null,
    is_system: true,
    tls_enabled: false,
  },
  {
    id: "dom_worker",
    hostname: "worker.production.localhost",
    environment_id: "env_shop_prod",
    target_type: "service",
    service_id: "svc_worker",
    deployment_id: null,
    is_system: true,
    tls_enabled: false,
  },
  {
    id: "dom_api_stg",
    hostname: "api.staging.localhost",
    environment_id: "env_shop_stg",
    target_type: "service",
    service_id: "svc_api_stg",
    deployment_id: null,
    is_system: true,
    tls_enabled: false,
  },
  {
    id: "dom_atlas_api",
    hostname: "atlas-api.production.localhost",
    environment_id: "env_atlas_prod",
    target_type: "service",
    service_id: "svc_atlas_api",
    deployment_id: null,
    is_system: true,
    tls_enabled: false,
  },
];

const deployments: Deployment[] = [
  {
    id: "dep_api_3",
    service_id: "svc_api",
    image_tag: "localhost:5000/svc_api:9f21ac4",
    commit_sha: "9f21ac4",
    status: "live",
    build_log_url: "/deployments/dep_api_3/logs",
    error_message: null,
    created_at: iso(T0 - 42 * min),
    became_live_at: iso(T0 - 40 * min),
  },
  {
    id: "dep_api_2",
    service_id: "svc_api",
    image_tag: "localhost:5000/svc_api:1b7de90",
    commit_sha: "1b7de90",
    status: "superseded",
    build_log_url: "/deployments/dep_api_2/logs",
    error_message: null,
    created_at: iso(T0 - 6 * 60 * min),
    became_live_at: iso(T0 - 6 * 60 * min + 2 * min),
  },
  {
    id: "dep_api_1",
    service_id: "svc_api",
    image_tag: "localhost:5000/svc_api:c30f118",
    commit_sha: "c30f118",
    status: "failed",
    build_log_url: "/deployments/dep_api_1/logs",
    error_message: "health check did not return 200 within 60s",
    created_at: iso(T0 - 26 * 60 * min),
    became_live_at: null,
  },
  {
    id: "dep_worker_1",
    service_id: "svc_worker",
    image_tag: "localhost:5000/svc_worker:9f21ac4",
    commit_sha: "9f21ac4",
    status: "live",
    build_log_url: "/deployments/dep_worker_1/logs",
    error_message: null,
    created_at: iso(T0 - 41 * min),
    became_live_at: iso(T0 - 39 * min),
  },
  {
    id: "dep_pg_1",
    service_id: "svc_postgres",
    image_tag: "postgres:16",
    commit_sha: "-",
    status: "live",
    build_log_url: null,
    error_message: null,
    created_at: iso(T0 - 30 * 24 * 60 * min),
    became_live_at: iso(T0 - 30 * 24 * 60 * min),
  },
  {
    id: "dep_web_1",
    service_id: "svc_web",
    image_tag: "localhost:5000/svc_web:44ba0e2",
    commit_sha: "44ba0e2",
    status: "live",
    build_log_url: "/deployments/dep_web_1/logs",
    error_message: null,
    created_at: iso(T0 - 3 * 60 * min),
    became_live_at: iso(T0 - 3 * 60 * min + min),
  },
  {
    id: "dep_apistg_1",
    service_id: "svc_api_stg",
    image_tag: "localhost:5000/svc_api_stg:aa10c9d",
    commit_sha: "aa10c9d",
    status: "failed",
    build_log_url: "/deployments/dep_apistg_1/logs",
    error_message: "buildkit: exit code 1 — `npm run build` failed",
    created_at: iso(T0 - 18 * min),
    became_live_at: null,
  },
  {
    id: "dep_atlas_1",
    service_id: "svc_atlas_api",
    image_tag: "localhost:5000/svc_atlas_api:70c1ee3",
    commit_sha: "70c1ee3",
    status: "live",
    build_log_url: "/deployments/dep_atlas_1/logs",
    error_message: null,
    created_at: iso(T0 - 9 * 60 * min),
    became_live_at: iso(T0 - 9 * 60 * min + min),
  },
];

const instances: Instance[] = [
  {
    id: "ins_api_3",
    deployment_id: "dep_api_3",
    node_id: "nod_local",
    container_id: "3f8a1c0b9e21",
    status: "healthy",
    wg_ip: "10.42.0.4",
    started_at: iso(T0 - 40 * min),
    stopped_at: null,
  },
  {
    id: "ins_api_2",
    deployment_id: "dep_api_2",
    node_id: "nod_local",
    container_id: "b71e0dd42a55",
    status: "stopped",
    wg_ip: "10.42.0.3",
    started_at: iso(T0 - 6 * 60 * min + 2 * min),
    stopped_at: iso(T0 - 40 * min),
  },
  {
    id: "ins_worker_1",
    deployment_id: "dep_worker_1",
    node_id: "nod_local",
    container_id: "cc02a4f7710d",
    status: "healthy",
    wg_ip: "10.42.0.5",
    started_at: iso(T0 - 39 * min),
    stopped_at: null,
  },
  {
    id: "ins_pg_1",
    deployment_id: "dep_pg_1",
    node_id: "nod_local",
    container_id: "9de1447f0a3b",
    status: "healthy",
    wg_ip: "10.42.0.2",
    started_at: iso(T0 - 30 * 24 * 60 * min),
    stopped_at: null,
  },
  {
    id: "ins_web_1",
    deployment_id: "dep_web_1",
    node_id: "nod_local",
    container_id: "1a5c7b3e88f0",
    status: "healthy",
    wg_ip: "10.42.0.6",
    started_at: iso(T0 - 3 * 60 * min + min),
    stopped_at: null,
  },
  {
    id: "ins_atlas_1",
    deployment_id: "dep_atlas_1",
    node_id: "nod_local",
    container_id: "6b0d9ee12c74",
    status: "healthy",
    wg_ip: "10.43.0.2",
    started_at: iso(T0 - 9 * 60 * min + min),
    stopped_at: null,
  },
];

const variables: Variable[] = [
  { id: "var_1", service_id: "svc_api", key: "DATABASE_URL", is_reference: true },
  { id: "var_2", service_id: "svc_api", key: "SESSION_SECRET", is_reference: false },
  { id: "var_3", service_id: "svc_api", key: "STRIPE_SECRET_KEY", is_reference: false },
  { id: "var_4", service_id: "svc_api", key: "LOG_LEVEL", is_reference: false },
  { id: "var_5", service_id: "svc_worker", key: "DATABASE_URL", is_reference: true },
  { id: "var_6", service_id: "svc_worker", key: "QUEUE_CONCURRENCY", is_reference: false },
  { id: "var_7", service_id: "svc_postgres", key: "POSTGRES_PASSWORD", is_reference: false },
  { id: "var_8", service_id: "svc_web", key: "API_BASE_URL", is_reference: true },
  { id: "var_9", service_id: "svc_api_stg", key: "DATABASE_URL", is_reference: true },
];

const buildLogs = new Map<string, string[]>([
  [
    "dep_api_3",
    [
      "#1 [internal] load build definition from Dockerfile.generated",
      "#1 transferring dockerfile: 612B done",
      "#2 [internal] load metadata for docker.io/library/node:20-alpine",
      "#3 [builder 1/5] FROM docker.io/library/node:20-alpine",
      "#4 [builder 2/5] COPY package.json package-lock.json ./",
      "#5 [builder 3/5] RUN npm ci --omit=dev",
      "#5 DONE 21.4s",
      "#6 [builder 4/5] COPY . .",
      "#7 [builder 5/5] RUN npm run build",
      "#7 DONE 11.9s",
      "#8 exporting to image",
      "#8 pushing localhost:5000/svc_api:9f21ac4 done",
      "build succeeded in 46.2s",
    ],
  ],
  [
    "dep_api_2",
    [
      "#1 [internal] load build definition from Dockerfile.generated",
      "#5 [builder 3/5] RUN npm ci --omit=dev",
      "#7 [builder 5/5] RUN npm run build",
      "#8 pushing localhost:5000/svc_api:1b7de90 done",
      "build succeeded in 44.8s",
    ],
  ],
  [
    "dep_api_1",
    [
      "#1 [internal] load build definition from Dockerfile.generated",
      "#5 [builder 3/5] RUN npm ci --omit=dev",
      "#8 pushing localhost:5000/svc_api:c30f118 done",
      "build succeeded in 51.0s",
      "health: GET http://172.18.0.9:3000/healthz -> connection refused",
      "health: GET http://172.18.0.9:3000/healthz -> connection refused",
      "health: timed out after 60s, rolling back",
    ],
  ],
  [
    "dep_worker_1",
    [
      "#1 [internal] load build definition from Dockerfile.generated",
      "#5 [builder 3/5] RUN npm ci --omit=dev",
      "#8 pushing localhost:5000/svc_worker:9f21ac4 done",
      "build succeeded in 39.1s",
    ],
  ],
  [
    "dep_web_1",
    [
      "#1 [internal] load build definition from Dockerfile.generated",
      "#4 [builder 2/4] RUN npm ci",
      "#5 [builder 3/4] RUN npm run build",
      "#6 [stage-1 1/2] FROM docker.io/library/nginx:alpine",
      "#7 [stage-1 2/2] COPY --from=builder /app/dist /usr/share/nginx/html",
      "#8 pushing localhost:5000/svc_web:44ba0e2 done",
      "build succeeded in 33.7s",
    ],
  ],
  [
    "dep_apistg_1",
    [
      "#1 [internal] load build definition from Dockerfile.generated",
      "#5 [builder 3/5] RUN npm ci --omit=dev",
      "#7 [builder 5/5] RUN npm run build",
      "#7 3.11 src/routes/auth.ts(41,18): error TS2554: Expected 2 arguments, but got 1.",
      "#7 ERROR: process \"/bin/sh -c npm run build\" did not complete successfully: exit code: 1",
      "build failed after 18.3s",
    ],
  ],
  ["dep_pg_1", ["postgres:16 pulled from upstream, no build performed"]],
  [
    "dep_atlas_1",
    [
      "#1 [internal] load build definition from Dockerfile",
      "#4 [2/4] RUN go mod download",
      "#5 [3/4] RUN go build -o /out/atlas ./cmd/atlas",
      "#6 pushing localhost:5000/svc_atlas_api:70c1ee3 done",
      "build succeeded in 28.4s",
    ],
  ],
]);

// --- Simulated deploy progression ----------------------------------------
//
// A deploy created through this mock walks queued → building → deploying →
// live on a wall clock, so the polling UI has something real to render. This
// is a stand-in for the background worker in Phase 1 step 5, nothing more.

const BUILD_MS = 4_000;
const DEPLOY_MS = 8_000;
const LINE_MS = 450;

const simulated = new Map<string, number>();

function simulatedStatus(startedAt: number): DeploymentStatus {
  const elapsed = Date.now() - startedAt;
  if (elapsed < 600) return "queued";
  if (elapsed < BUILD_MS) return "building";
  if (elapsed < DEPLOY_MS) return "deploying";
  return "live";
}

function simulatedLines(deploymentId: string, startedAt: number): string[] {
  const all = buildLogs.get(deploymentId) ?? [];
  const elapsed = Date.now() - startedAt;
  const visible = Math.max(0, Math.min(all.length, Math.floor(elapsed / LINE_MS)));
  return all.slice(0, visible);
}

/**
 * Advance any simulated deployment that has finished. Called at the top of
 * every read so the mock is internally consistent no matter what is polled.
 */
function tick(): void {
  for (const [deploymentId, startedAt] of simulated) {
    const deployment = deployments.find((d) => d.id === deploymentId);
    if (!deployment) {
      simulated.delete(deploymentId);
      continue;
    }
    const next = simulatedStatus(startedAt);
    deployment.status = next;

    if (next === "deploying") {
      // D11: reaching `deploying` supersedes every older non-terminal
      // deployment for the service and drains its instances.
      for (const other of deployments) {
        if (other.service_id !== deployment.service_id) continue;
        if (other.id === deployment.id) continue;
        if (other.status === "live" || other.status === "deploying") {
          other.status = "superseded";
          for (const instance of instances) {
            if (instance.deployment_id === other.id && instance.status === "healthy") {
              instance.status = "draining";
            }
          }
        }
      }
      if (!instances.some((i) => i.deployment_id === deployment.id)) {
        instances.push({
          id: nextId("ins"),
          deployment_id: deployment.id,
          node_id: "nod_local",
          container_id: nextId("ctr").slice(4, 16),
          status: "starting",
          wg_ip: null,
          started_at: iso(Date.now()),
          stopped_at: null,
        });
      }
    }

    if (next === "live") {
      deployment.became_live_at = deployment.became_live_at ?? iso(startedAt + DEPLOY_MS);
      for (const instance of instances) {
        if (instance.deployment_id === deployment.id) instance.status = "healthy";
        else if (instance.status === "draining") {
          const owner = deployments.find((d) => d.id === instance.deployment_id);
          if (owner && owner.service_id === deployment.service_id) {
            instance.status = "stopped";
            instance.stopped_at = iso(Date.now());
          }
        }
      }
      simulated.delete(deploymentId);
    }
  }
}

function latency(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 70));
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

function notFound(what: string, id: string): never {
  throw new Error(`${what} ${id} not found`);
}

// --- Reads ----------------------------------------------------------------

export async function listProjects(): Promise<Project[]> {
  tick();
  await latency();
  return clone(projects);
}

export async function listEnvironments(projectId: string): Promise<Environment[]> {
  tick();
  await latency();
  return clone(environments.filter((e) => e.project_id === projectId));
}

export async function listServices(environmentId: string): Promise<Service[]> {
  tick();
  await latency();
  return clone(services.filter((s) => s.environment_id === environmentId));
}

export async function getService(serviceId: string): Promise<Service> {
  tick();
  await latency();
  const service = services.find((s) => s.id === serviceId);
  return service ? clone(service) : notFound("service", serviceId);
}

export async function listDomains(environmentId: string): Promise<Domain[]> {
  tick();
  await latency();
  return clone(domains.filter((d) => d.environment_id === environmentId));
}

export async function listDeployments(serviceId: string): Promise<Deployment[]> {
  tick();
  await latency();
  return clone(
    deployments
      .filter((d) => d.service_id === serviceId)
      .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at)),
  );
}

export async function listInstances(serviceId: string): Promise<Instance[]> {
  tick();
  await latency();
  const owned = new Set(deployments.filter((d) => d.service_id === serviceId).map((d) => d.id));
  return clone(instances.filter((i) => owned.has(i.deployment_id)));
}

export async function listVariables(serviceId: string): Promise<Variable[]> {
  tick();
  await latency();
  return clone(
    variables.filter((v) => v.service_id === serviceId).sort((a, b) => a.key.localeCompare(b.key)),
  );
}

export async function getBuildLog(deploymentId: string): Promise<BuildLog> {
  tick();
  await latency();
  const startedAt = simulated.get(deploymentId);
  if (startedAt !== undefined) {
    return {
      deployment_id: deploymentId,
      lines: simulatedLines(deploymentId, startedAt),
      complete: false,
    };
  }
  return {
    deployment_id: deploymentId,
    lines: clone(buildLogs.get(deploymentId) ?? []),
    complete: true,
  };
}

// --- Writes ---------------------------------------------------------------

export async function updateService(serviceId: string, patch: ServiceUpdate): Promise<Service> {
  tick();
  await latency();
  const service = services.find((s) => s.id === serviceId);
  if (!service) return notFound("service", serviceId);
  if (patch.canvas_x !== undefined) service.canvas_x = patch.canvas_x;
  if (patch.canvas_y !== undefined) service.canvas_y = patch.canvas_y;
  return clone(service);
}

export async function createDeployment(serviceId: string): Promise<Deployment> {
  tick();
  await latency();
  const service = services.find((s) => s.id === serviceId);
  if (!service) return notFound("service", serviceId);

  const sha = Math.random().toString(16).slice(2, 9);
  const id = nextId("dep");
  const deployment: Deployment = {
    id,
    service_id: serviceId,
    image_tag: `localhost:5000/${serviceId}:${sha}`,
    commit_sha: sha,
    status: "queued",
    build_log_url: `/deployments/${id}/logs`,
    error_message: null,
    created_at: iso(Date.now()),
    became_live_at: null,
  };
  deployments.push(deployment);
  buildLogs.set(id, [
    `#1 [internal] load build definition from Dockerfile.generated`,
    `#1 transferring dockerfile: 612B done`,
    `#2 [internal] load metadata for base image`,
    `#3 [builder 1/5] FROM base`,
    `#4 [builder 2/5] COPY manifest ./`,
    `#5 [builder 3/5] RUN install dependencies`,
    `#6 [builder 4/5] COPY . .`,
    `#7 [builder 5/5] RUN build`,
    `#8 exporting to image`,
    `#8 pushing localhost:5000/${serviceId}:${sha} done`,
    `build succeeded`,
    `health: GET ${service.health_check_path ?? "/"} -> 200`,
    `traefik: router written, ${service.name} is live`,
  ]);
  simulated.set(id, Date.now());
  return clone(deployment);
}

export async function putVariable(
  serviceId: string,
  key: string,
  value: string,
): Promise<Variable> {
  tick();
  await latency();
  // The value is intentionally dropped on the floor. The real control plane
  // Fernet-encrypts it into `Variable.value_encrypted` and never hands it back.
  const isReference = /^\$\{\{.+\}\}$/.test(value.trim());
  const existing = variables.find((v) => v.service_id === serviceId && v.key === key);
  if (existing) {
    existing.is_reference = isReference;
    return clone(existing);
  }
  const created: Variable = {
    id: nextId("var"),
    service_id: serviceId,
    key,
    is_reference: isReference,
  };
  variables.push(created);
  return clone(created);
}

export async function deleteVariable(serviceId: string, key: string): Promise<void> {
  tick();
  await latency();
  const index = variables.findIndex((v) => v.service_id === serviceId && v.key === key);
  if (index >= 0) variables.splice(index, 1);
}
