import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { BackToWorkspaceButton } from "./top-bar";

it("gives an environment operator a labeled path back to the workspace", () => {
  render(<BackToWorkspaceButton />);

  const link = screen.getByRole("link", { name: "Back to workspace" });
  expect(link.getAttribute("href")).toBe("/dashboard");
});
