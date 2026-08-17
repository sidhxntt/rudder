import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { ServiceTabs } from "./detail-panel";

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
