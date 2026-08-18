import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";

import { ProjectSettings } from "./project-settings";

const replace = vi.fn();
const deleteProject = vi.fn();

vi.mock("next/navigation", () => ({
  useParams: () => ({ projectId: "project-1" }),
  useRouter: () => ({ replace }),
}));

vi.mock("@/lib/queries", () => ({
  useProjects: () => ({
    data: [{ id: "project-1", name: "Checkout", owner_id: "user-1", created_at: "2026-08-18T00:00:00Z" }],
  }),
  useUpdateProject: () => ({ isPending: false, mutateAsync: vi.fn() }),
  useDeleteProject: () => ({ isPending: false, mutateAsync: deleteProject }),
}));

beforeEach(() => {
  replace.mockReset();
  deleteProject.mockReset();
  deleteProject.mockResolvedValue(undefined);
  vi.spyOn(window, "confirm").mockReturnValue(true);
});

it("returns to the authenticated dashboard after a project is deleted", async () => {
  const user = userEvent.setup();
  render(<ProjectSettings />);

  await user.type(screen.getByLabelText("Confirm project deletion"), "Checkout");
  await user.click(screen.getByRole("button", { name: "Delete project" }));

  expect(deleteProject).toHaveBeenCalledWith("project-1");
  expect(replace).toHaveBeenCalledWith("/dashboard");
});
