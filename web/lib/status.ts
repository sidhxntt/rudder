import type { Deployment, Domain, Instance, Service, ServiceStatus } from "./types";

/**
 * `Service` has no status column — the PRD data model deliberately keeps
 * Deployment (intent) and Instance (running container) as the record of truth.
 * The canvas needs one word per node, so it is derived here, in one place.
 *
 * The vocabularies this reads are the API's own, verified against the live
 * OpenAPI document: DeploymentStatus ∈ {queued, building, deploying, live,
 * failed, superseded}, InstanceStatus ∈ {starting, healthy, unhealthy,
 * draining, stopped}.
 *
 * Precedence, most urgent first:
 *   building  — something is in flight right now
 *   live      — a live Deployment with at least one healthy Instance
 *   draining  — instances are winding down and nothing healthy is left
 *   failed    — the newest Deployment failed, or the live Deployment has no
 *               healthy Instance
 *   unknown   — never deployed
 *
 * The fourth case is the one that matters and the one a `Service.status` column
 * could never express. `Deployment.status = live` is *intent*: the control
 * plane shifted traffic and stopped writing. If the container has since died,
 * its Instance is `stopped` or `unhealthy` while the Deployment still says
 * `live` — and the public URL 503s. That is `failed` here, never `live`.
 */
export function deriveServiceStatus(
  deployments: readonly Deployment[],
  instances: readonly Instance[],
): ServiceStatus {
  if (deployments.length === 0) return "unknown";

  const inFlight = deployments.some(
    (d) => d.status === "queued" || d.status === "building" || d.status === "deploying",
  );
  if (inFlight) return "building";

  const live = deployments.find((d) => d.status === "live");
  if (live) {
    const own = instances.filter((i) => i.deployment_id === live.id);
    if (own.some((i) => i.status === "healthy")) return "live";
    if (own.some((i) => i.status === "starting")) return "building";
    if (own.some((i) => i.status === "draining")) return "draining";
    // No instance at all, or every one of them stopped/unhealthy. Nothing is
    // serving this deployment.
    return "failed";
  }

  // The API returns deployments newest-first, but ordering is not something to
  // depend on for a status the whole canvas reads — pick the newest by clock.
  const newest = latestDeployment(deployments);
  if (newest && newest.status === "failed") return "failed";
  if (instances.some((i) => i.status === "draining")) return "draining";
  return "unknown";
}

/** The most recently created deployment, independent of API response ordering. */
export function latestDeployment(deployments: readonly Deployment[]): Deployment | null {
  let newest: Deployment | null = null;
  for (const deployment of deployments) {
    if (!newest || Date.parse(deployment.created_at) > Date.parse(newest.created_at)) {
      newest = deployment;
    }
  }
  return newest;
}

export const STATUS_LABEL: Record<ServiceStatus, string> = {
  live: "live",
  building: "building",
  failed: "failed",
  draining: "draining",
  unknown: "no deploys",
};

/** Tailwind colour utility per status. Maps to the semantic tokens in D5. */
export const STATUS_TEXT: Record<ServiceStatus, string> = {
  live: "text-status-live",
  building: "text-status-building",
  failed: "text-status-failed",
  draining: "text-status-draining",
  unknown: "text-status-unknown",
};

export const STATUS_BG: Record<ServiceStatus, string> = {
  live: "bg-status-live",
  building: "bg-status-building",
  failed: "bg-status-failed",
  draining: "bg-status-draining",
  unknown: "bg-status-unknown",
};

/**
 * The public URL of a service is its system Domain (D15 — routing is keyed on
 * Domain, never on Service). A database has none, by design.
 */
export function serviceUrl(service: Service, domains: readonly Domain[]): string | null {
  const domain = domains.find(
    (d) => d.target_type === "service" && d.service_id === service.id && d.is_system,
  );
  if (!domain) return null;
  return `${domain.tls_enabled ? "https" : "http"}://${domain.hostname}`;
}

export function shortAgo(isoDate: string | null): string {
  if (!isoDate) return "—";
  const seconds = Math.max(0, Math.round((Date.now() - Date.parse(isoDate)) / 1000));
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}
