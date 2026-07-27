import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { DeployHistory } from "./deploy-history";

it("offers restore only for an earlier successful immutable release", async () => {
  const onRollback = vi.fn();
  const user = userEvent.setup();

  render(
    <DeployHistory
      selectedId="live"
      onSelect={vi.fn()}
      onRollback={onRollback}
      deployments={[
        {
          id: "live",
          service_id: "service",
          status: "live",
          image_tag: "registry/app:new",
          commit_sha: "newcommit",
          error_message: null,
          created_at: "2026-07-27T00:00:00Z",
          became_live_at: "2026-07-27T00:01:00Z",
        },
        {
          id: "previous",
          service_id: "service",
          status: "superseded",
          image_tag: "registry/app:known-good",
          commit_sha: "oldcommit",
          error_message: null,
          created_at: "2026-07-26T00:00:00Z",
          became_live_at: "2026-07-26T00:01:00Z",
        },
      ]}
    />,
  );

  expect(screen.getAllByRole("button", { name: "Restore" })).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: "Restore" }));
  expect(onRollback).toHaveBeenCalledWith("previous");
});
