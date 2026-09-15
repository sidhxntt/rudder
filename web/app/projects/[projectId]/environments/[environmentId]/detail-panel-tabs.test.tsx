import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import type { Service } from "@/lib/types";

const { deployMutate } = vi.hoisted(() => ({ deployMutate: vi.fn() }));

vi.mock("@/lib/queries", () => ({
  useDeployments: () => ({ data: [] }),
  useInstances: () => ({ data: [] }),
  useDeploy: () => ({ isPending: false, isError: false, mutate: deployMutate }),
  useRollbackDeployment: () => ({ isPending: false, isError: false, mutate: vi.fn() }),
  useRenameService: () => ({ mutateAsync: vi.fn() }),
}));

import { DetailPanel, ServiceTabs } from "./detail-panel";

it("exposes service views as an accessible tablist", async () => {
  const user = userEvent.setup();
  const onTabChange = vi.fn();

  render(<ServiceTabs tab="logs" onTabChange={onTabChange} />);

  expect(screen.getByRole("tablist", { name: "Service views" })).toBeTruthy();
  expect(screen.getByRole("tab", { name: "Build logs" }).getAttribute("aria-selected")).toBe("true");
  expect(screen.getByRole("tab", { name: "Analytics" }).getAttribute("aria-selected")).toBe("false");

  await user.click(screen.getByRole("tab", { name: "Analytics" }));

  expect(onTabChange).toHaveBeenCalledWith("analytics");
});

it("redeploys the owning Compose release from a managed member's Deploys tab", async () => {
  const user = userEvent.setup();
  const service = {
    id: "postgres",
    environment_id: "environment",
    name: "postgres",
    kind: "database",
    source_repo: null,
    source_branch: "main",
    dockerfile_path: null,
    build_config: { compose_role: "database" },
    start_command: null,
    container_port: 5432,
    health_check_path: "/",
    health_check_port: null,
    cpu_limit: 1,
    memory_limit_mb: 512,
    replica_count: 1,
    canvas_x: 0,
    canvas_y: 0,
    created_at: "2026-08-19T00:00:00Z",
  } as Service;

  render(
    <DetailPanel
      service={service}
      url={null}
      domains={[]}
      managedByServiceId="compose-release"
      onClose={vi.fn()}
    />,
  );

  await user.click(screen.getByRole("tab", { name: "Deploys" }));
  await user.click(screen.getByRole("button", { name: "Redeploy" }));

  expect(deployMutate).toHaveBeenCalledOnce();
});
