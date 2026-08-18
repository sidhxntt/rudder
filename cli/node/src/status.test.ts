import { describe, expect, it } from "vitest";

import { formatCompactStatus, toStatusAdvisorInput, type StatusRow } from "./status.js";

const rows: StatusRow[] = [
  {
    service: { id: "app-1", name: "app", kind: "app" },
    deployments: [{ id: "release-1", status: "live", commit_sha: "106b06e83c903352050942790f1b8569d9de62f7", error_message: null }],
    instances: [{ deployment_id: "release-1", status: "healthy" }, { deployment_id: "old-release", status: "stopped" }],
  },
  {
    service: { id: "db-1", name: "postgres", kind: "database", build_config: { managed_by_service_id: "app-1" } },
    deployments: [{ id: "release-1", status: "failed", commit_sha: null, error_message: "Could not start the Compose project. compose_error: registry unavailable" }],
    instances: [],
  },
];

describe("formatCompactStatus", () => {
  it("summarizes the latest deployment and healthy instances for each service", () => {
    const output = formatCompactStatus(rows);

    expect(output).toContain("Rudder status · 2 services");
    expect(output).toContain("app");
    expect(output).toContain("live");
    expect(output).toContain("1/1 release containers healthy");
    expect(output).toContain("106b06e");
  });

  it("marks a failed latest deployment with a short readable reason", () => {
    const output = formatCompactStatus(rows);

    expect(output).toContain("postgres");
    expect(output).toContain("failed");
    expect(output).toContain("registry unavailable");
    expect(output).toContain("managed by app");
  });
});

it("builds a bounded status snapshot for the read-only AI explanation", () => {
  const input = toStatusAdvisorInput(rows);

  expect(input.logs).toEqual(expect.arrayContaining([expect.stringContaining("app: live, 1/1 release containers healthy, commit 106b06e")]));
  expect(input.logs).toEqual(expect.arrayContaining([expect.stringContaining("postgres: failed, managed by app")]));
  expect(input.logs.join("\n")).not.toContain("service_id");
  expect(input.service_config).toEqual({ source: "rudder-cli-status" });
});
