export type StatusRow = {
  service: { id: string; name: string; kind?: string | null; build_config?: { managed_by_service_id?: string } | null };
  deployments: Array<{ id?: string; status?: string | null; commit_sha?: string | null; error_message?: string | null }>;
  instances: Array<{ deployment_id?: string; status?: string | null }>;
};

type StatusAdvisorInput = {
  logs: string[];
  service_config: { source: "rudder-cli-status" };
};

export function formatCompactStatus(rows: StatusRow[]): string {
  const namesById = new Map(rows.map(({ service }) => [service.id, service.name]));
  const lines = rows.map(({ service, deployments, instances }) => {
    const latest = deployments[0];
    const state = latest?.status ?? "not deployed";
    const management = managedBy(service, namesById);
    const health = management ?? (latest ? releaseHealth(latest.id, instances) : undefined);
    const commit = latest?.commit_sha ? ` · ${latest.commit_sha.slice(0, 7)}` : "";
    const error = latest?.error_message ? `\n  ↳ ${shortError(latest.error_message)}` : "";
    return `${service.name} · ${state}${health ? ` · ${health}` : ""}${commit}${error}`;
  });
  return [`Rudder status · ${rows.length} service${rows.length === 1 ? "" : "s"}`, ...lines].join("\n");
}

export function toStatusAdvisorInput(rows: StatusRow[]): StatusAdvisorInput {
  const namesById = new Map(rows.map(({ service }) => [service.id, service.name]));
  return {
    service_config: { source: "rudder-cli-status" },
    logs: rows.map(({ service, deployments, instances }) => {
      const latest = deployments[0];
      const health = managedBy(service, namesById) ?? releaseHealth(latest?.id, instances);
      const commit = latest?.commit_sha ? `, commit ${latest.commit_sha.slice(0, 7)}` : "";
      const failure = latest?.error_message ? `, last error: ${shortError(latest.error_message)}` : "";
      return `${service.name}: ${latest?.status ?? "not deployed"}, ${health}${commit}${failure}`;
    }),
  };
}

function managedBy(service: StatusRow["service"], namesById: Map<string, string>): string | undefined {
  const ownerId = service.build_config?.managed_by_service_id;
  return ownerId ? `managed by ${namesById.get(ownerId) ?? "release owner"}` : undefined;
}

function releaseHealth(deploymentId: string | undefined, instances: StatusRow["instances"]): string {
  const current = deploymentId ? instances.filter(instance => instance.deployment_id === deploymentId) : [];
  const healthy = current.filter(instance => instance.status === "healthy").length;
  return `${healthy}/${current.length} release containers healthy`;
}

function shortError(message: string): string {
  const normalized = message.replace(/\s+/g, " ").trim();
  const marker = normalized.lastIndexOf("compose_error:");
  const useful = marker >= 0 ? normalized.slice(marker + "compose_error:".length).trim() : normalized;
  return useful.slice(0, 220);
}
