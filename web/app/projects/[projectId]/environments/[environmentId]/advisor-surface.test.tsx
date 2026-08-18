import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  acceptAdvisorItem: vi.fn(),
  scanAdvisor: vi.fn(),
}));

vi.mock("@/lib/api", () => api);
vi.mock("@/lib/queries", () => ({
  useServices: () => ({ data: [{ id: "service-1", name: "api" }] }),
}));

import { AdvisorSurface } from "./advisor-surface";

it("requires and sends a target service when accepting a variable proposal", async () => {
  api.scanAdvisor.mockResolvedValue({
    items: [{ id: "variable:DATABASE_URL", kind: "variable", payload: { key: "DATABASE_URL", value: "postgres://db" } }],
  });
  api.acceptAdvisorItem.mockResolvedValue({});
  const user = userEvent.setup();
  render(<AdvisorSurface environmentId="environment-1" />);

  await user.type(screen.getByPlaceholderText("checkout path relative to advisor root"), ".");
  await user.click(screen.getByRole("button", { name: "Scan" }));
  await screen.findByRole("button", { name: "Accept this item" });

  await user.click(screen.getByRole("button", { name: "Accept this item" }));
  expect(screen.getByText("Choose a target service before accepting this variable.")).toBeTruthy();
  expect(api.acceptAdvisorItem).not.toHaveBeenCalled();

  await user.selectOptions(screen.getByLabelText("Target service for DATABASE_URL"), "service-1");
  await user.click(screen.getByRole("button", { name: "Accept this item" }));

  await waitFor(() => expect(api.acceptAdvisorItem).toHaveBeenCalledWith(
    "environment-1",
    expect.objectContaining({ kind: "variable" }),
    "service-1",
  ));
});
