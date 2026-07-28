import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hooks = vi.hoisted(() => {
  const mutation = { isPending: false, error: null, mutate: vi.fn() };
  return {
    operations: {
      isLoading: false,
      isError: false,
      data: {
        desired: {},
        observed: { reconciliation: { status: "healthy" } },
        version: 1,
        pending_reconciliation: false,
        updated_at: "2026-07-28T00:00:00Z",
        history: [
          {
            id: "operation-1",
            service_id: "service-1",
            kind: "scale",
            status: "healthy",
            requested: { replicas: 2 },
            observed: {},
            error_message: null,
            created_at: "2026-07-28T00:00:00Z",
            completed_at: "2026-07-28T00:00:01Z",
          },
        ],
        etag: '"1"',
      },
    },
    deployments: { data: [{ id: "old", service_id: "service-1", status: "superseded", image_tag: "registry/app:old", commit_sha: "old", error_message: null, created_at: "2026-07-27T00:00:00Z", became_live_at: "2026-07-27T00:00:01Z" }] },
    mutation,
  };
});

vi.mock("@/lib/queries", () => ({
  useServiceOperations: () => hooks.operations,
  useDeployments: () => hooks.deployments,
  useScaleOperation: () => hooks.mutation,
  useResourcesOperation: () => hooks.mutation,
  useAutoscalingOperation: () => hooks.mutation,
  usePlacementOperation: () => hooks.mutation,
  useRolloutOperation: () => hooks.mutation,
  useOperationRollback: () => hooks.mutation,
  useBackupOperation: () => hooks.mutation,
  useReadReplicasOperation: () => hooks.mutation,
  useStorageOperation: () => hooks.mutation,
  useScheduleOperation: () => hooks.mutation,
  useJobOperation: () => hooks.mutation,
  useObservabilityOperation: () => hooks.mutation,
  useDeleteScheduleOperation: () => hooks.mutation,
}));

import { Operations } from "./operations";

const app = {
  id: "service-1",
  environment_id: "environment-1",
  name: "api",
  kind: "app" as const,
  source_repo: "acme/api",
  source_branch: "main",
  dockerfile_path: null,
  build_config: {},
  start_command: null,
  container_port: 3000,
  health_check_path: "/health",
  health_check_port: null,
  cpu_limit: 1,
  memory_limit_mb: 512,
  replica_count: 1,
  canvas_x: 0,
  canvas_y: 0,
  created_at: "2026-07-28T00:00:00Z",
};

describe("Operations", () => {
  beforeEach(() => hooks.mutation.mutate.mockClear());

  it("exposes workload controls and labels immutable restore as no-build", () => {
    render(<Operations service={app} />);

    expect(screen.getByRole("heading", { name: "Run" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Apply scale" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Restore" })).toBeTruthy();
    expect(screen.getByText(/No source build is started/)).toBeTruthy();
    expect(screen.getByText("scale")).toBeTruthy();
  });

  it("submits a manually requested replica count", async () => {
    const user = userEvent.setup();
    render(<Operations service={app} />);

    const field = screen.getByRole("textbox", { name: "Manual replicas" });
    await user.clear(field);
    await user.type(field, "3");
    await user.click(screen.getByRole("button", { name: "Apply scale" }));

    expect(hooks.mutation.mutate).toHaveBeenCalledWith(3);
  });

  it("does not expose database write controls for an application", () => {
    render(<Operations service={app} />);
    expect(screen.getByText("Data controls are available only for managed database services.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Create backup" })).toBeNull();
  });
});
