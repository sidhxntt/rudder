import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, test, vi } from "vitest";

import { AssistantDock } from "./assistant-dock";

describe("AssistantDock", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("opens from the lower-left dock, keeps its read-only boundary, and renders sourced replies", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      model: "rudder-readonly-1",
      message: {
        role: "assistant",
        content: "The API service is healthy and has no pending rollout.",
        sources: [{ label: "API service", href: "/services/api" }],
      },
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    render(<AssistantDock environmentId="env one" />);

    const trigger = screen.getByRole("button", { name: "Ask Rudder" });
    expect(trigger.parentElement?.getAttribute("class")).toContain("bottom-5");
    expect(trigger.parentElement?.getAttribute("class")).toContain("left-5");
    expect(screen.queryByRole("dialog", { name: "Ask Rudder" })).toBeNull();

    await userEvent.click(trigger);
    expect(screen.getByRole("dialog", { name: "Ask Rudder" })).toBeTruthy();
    expect(screen.getByText("Read-only project context")).toBeTruthy();
    expect(screen.getByText("What is the current release state?")).toBeTruthy();

    await userEvent.type(screen.getByLabelText("Ask a question about this project"), "Is API healthy?");
    fireEvent.submit(screen.getByRole("form", { name: "Ask Rudder" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith("/api/environments/env%20one/assistant/messages", expect.objectContaining({
      method: "POST",
      credentials: "same-origin",
      body: JSON.stringify({ message: "Is API healthy?", prior_turns: [] }),
    }));
    expect(await screen.findByText("The API service is healthy and has no pending rollout.")).toBeTruthy();
    expect(screen.getByRole("link", { name: "API service" }).getAttribute("href")).toBe("/services/api");
    expect(screen.getByText("rudder-readonly-1")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /deploy|accept|rollback/i })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Close Ask Rudder" }));
    expect(screen.queryByRole("dialog", { name: "Ask Rudder" })).toBeNull();
  });
});
