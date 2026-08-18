export type StatusRow = {
  service: { id: string; name: string; kind?: string | null };
  deployments: Array<{ status?: string | null; commit_sha?: string | null; error_message?: string | null }>;
  instances: Array<{ status?: string | null }>;
};

type StatusAdvisorInput = {
  logs: string[];
  service_config: { source: "rudder-cli-status" };
};

export function formatCompactStatus(rows: StatusRow[]): string {
  const lines = rows.map(({ service, deployments, instances }) => {
    const latest = deployments[0];
    const state = latest?.status ?? "not deployed";
    const healthy = instances.filter(instance => instance.status === "healthy").length;
    const health = `${healthy}/${instances.length} healthy`;
    const commit = latest?.commit_sha ? ` · ${latest.commit_sha.slice(0, 7)}` : "";
    const error = latest?.error_message ? `\n  ↳ ${shortError(latest.error_message)}` : "";
    return `${service.name} · ${state} · ${health}${commit}${error}`;
  });
  return [`Rudder status · ${rows.length} service${rows.length === 1 ? "" : "s"}`, ...lines].join("\n");
}

export function toStatusAdvisorInput(rows: StatusRow[]): StatusAdvisorInput {
  return {
    service_config: { source: "rudder-cli-status" },
    logs: rows.map(({ service, deployments, instances }) => {
      const latest = deployments[0];
      const healthy = instances.filter(instance => instance.status === "healthy").length;
      const commit = latest?.commit_sha ? `, commit ${latest.commit_sha.slice(0, 7)}` : "";
      const failure = latest?.error_message ? `, last error: ${shortError(latest.error_message)}` : "";
      return `${service.name}: ${latest?.status ?? "not deployed"}, ${healthy}/${instances.length} healthy${commit}${failure}`;
    }),
  };
}

function shortError(message: string): string {
  const normalized = message.replace(/\s+/g, " ").trim();
  const marker = normalized.lastIndexOf("compose_error:");
  const useful = marker >= 0 ? normalized.slice(marker + "compose_error:".length).trim() : normalized;
  return useful.slice(0, 220);
}
