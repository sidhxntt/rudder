import type { Deployment, Domain, Instance, Service, ServiceStatus } from "./types";

/**
 * `Service` has no status column — the PRD data model deliberately keeps
 * Deployment (intent) and Instance (running container) as the record of truth.
 * The canvas needs one word per node, so it is derived here, in one place.
 *
 * Precedence, most urgent first:
 *   building  — something is in flight right now
 *   live      — a live Deployment with at least one healthy Instance
 *   draining  — instances are winding down and nothing healthy is left
 *   failed    — the newest Deployment failed, or the live one has no healthy
 *               instance (the "docker kill" case in Phase 1 → Verify step 4)
 *   unknown   — never deployed
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
    return "failed";
  }

  const newest = deployments[0];
  if (newest && newest.status === "failed") return "failed";
  if (instances.some((i) => i.status === "draining")) return "draining";
  return "unknown";
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
