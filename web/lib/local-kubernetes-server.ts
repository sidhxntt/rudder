import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);
const HEALTH_TIMEOUT_MS = 180_000;
const HEALTH_POLL_MS = 1_000;

export type MakeRunner = (target: "kind-up" | "kind-control-plane", rootDir: string) => Promise<void>;
export type HealthWaiter = () => Promise<void>;
export type RuntimeReadinessCheck = () => Promise<boolean>;
type HealthResponse = Pick<Response, "ok" | "status" | "json">;
type HealthRequester = () => Promise<HealthResponse>;

let bootstrapInFlight: Promise<void> | undefined;

export function isLocalKubernetesAutoBootstrapEnabled(
  environment: NodeJS.ProcessEnv = process.env,
): boolean {
  return environment.NODE_ENV !== "production" && environment.RUDDER_LOCAL_KUBERNETES_AUTO_BOOTSTRAP !== "false";
}

export async function bootstrapLocalKubernetesRuntime({
  rootDir = findRudderRoot(),
  runMake = runMakeTarget,
  waitForHealth = waitForKubernetesControlPlane,
  isReady = isLocalKindRuntimeReady,
}: {
  rootDir?: string;
  runMake?: MakeRunner;
  waitForHealth?: HealthWaiter;
  isReady?: RuntimeReadinessCheck;
} = {}): Promise<void> {
  if (await isReady()) return;
  await runMake("kind-up", rootDir);
  await runMake("kind-control-plane", rootDir);
  await waitForHealth();
}

/**
 * Serializes first-deploy setup. Kind and Docker Compose are shared host
 * resources, so two browser tabs must reuse the same bootstrap work.
 */
export function ensureLocalKubernetesRuntime(): Promise<void> {
  if (!isLocalKubernetesAutoBootstrapEnabled()) return Promise.resolve();
  if (!bootstrapInFlight) {
    bootstrapInFlight = bootstrapLocalKubernetesRuntime().finally(() => {
      bootstrapInFlight = undefined;
    });
  }
  return bootstrapInFlight;
}

function findRudderRoot(start = process.cwd()): string {
  let current = resolve(start);
  while (dirname(current) !== current) {
    if (existsSync(join(current, "Makefile")) && existsSync(join(current, "docker-compose.dev.yml"))) {
      return current;
    }
    current = dirname(current);
  }
  throw new Error("Could not find the Rudder repository root for local Kubernetes setup.");
}

async function runMakeTarget(target: "kind-up" | "kind-control-plane", rootDir: string): Promise<void> {
  await execFileAsync("make", [target], {
    cwd: rootDir,
    env: process.env,
    maxBuffer: 2 * 1024 * 1024,
  });
}

export async function waitForKubernetesControlPlane({
  request = () => fetch(controlPlaneHealthUrl(), { cache: "no-store" }),
  timeoutMs = HEALTH_TIMEOUT_MS,
  pollMs = HEALTH_POLL_MS,
}: {
  request?: HealthRequester;
  timeoutMs?: number;
  pollMs?: number;
} = {}): Promise<void> {
  const deadline = Date.now() + timeoutMs;
  let lastError = "control plane did not respond";

  while (Date.now() < deadline) {
    try {
      const response = await request();
      if (response.ok) {
        const body = (await response.json()) as { runtime?: string };
        if (body.runtime === "kubernetes") return;
        lastError = `control plane is still running the ${body.runtime ?? "unknown"} runtime`;
      } else {
        lastError = `control plane returned HTTP ${response.status}`;
      }
    } catch (error) {
      lastError = error instanceof Error ? error.message : String(error);
    }
    await new Promise((resolveSleep) => setTimeout(resolveSleep, pollMs));
  }

  throw new Error(`Local Kubernetes runtime started, but ${lastError}.`);
}

async function isLocalKindRuntimeReady(): Promise<boolean> {
  try {
    const [{ stdout }, response] = await Promise.all([
      execFileAsync("kind", ["get", "clusters"], { maxBuffer: 64 * 1024 }),
      fetch(controlPlaneHealthUrl(), { cache: "no-store" }),
    ]);
    if (!stdout.split(/\r?\n/).includes("rudder-kind") || !response.ok) return false;
    const body = (await response.json()) as { runtime?: string };
    return body.runtime === "kubernetes";
  } catch {
    return false;
  }
}

function controlPlaneHealthUrl(): URL {
  return new URL("/healthz", process.env.RUDDER_API_URL ?? "http://localhost:8000");
}
