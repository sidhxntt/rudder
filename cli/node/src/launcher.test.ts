import { describe, expect, it, vi } from "vitest";

const prompts = vi.hoisted(() => ({
  cancel: vi.fn(),
  intro: vi.fn(),
  isCancel: vi.fn((value: unknown) => value === Symbol.for("cancel")),
  outro: vi.fn(),
  select: vi.fn(),
  spinner: vi.fn(),
}));

vi.mock("@clack/prompts", () => prompts);

import { runLauncher } from "./launcher.js";

describe("runLauncher", () => {
  it("clears the terminal and dispatches Deploy through its injected callback", async () => {
    const spinner = { start: vi.fn(), stop: vi.fn() };
    prompts.spinner.mockReturnValue(spinner);
    prompts.select.mockResolvedValueOnce("deploy").mockResolvedValueOnce("exit");
    const actions = { chooseTarget: vi.fn(), deploy: vi.fn(), status: vi.fn(), logs: vi.fn(), services: vi.fn(), variables: vi.fn(), advisor: vi.fn(), signOut: vi.fn() };
    const clear = vi.fn();

    await runLauncher({ actions, clear });

    expect(clear).toHaveBeenCalledOnce();
    expect(prompts.intro).toHaveBeenCalledWith("Rudder control plane");
    expect(actions.deploy).toHaveBeenCalledOnce();
    expect(spinner.start).toHaveBeenCalledWith("Deploy");
    expect(prompts.outro).toHaveBeenCalledWith("Until next time.");
  });

  it("cancels without invoking an action", async () => {
    prompts.select.mockResolvedValue(Symbol.for("cancel"));
    const actions = { chooseTarget: vi.fn(), deploy: vi.fn(), status: vi.fn(), logs: vi.fn(), services: vi.fn(), variables: vi.fn(), advisor: vi.fn(), signOut: vi.fn() };

    await runLauncher({ actions, clear: vi.fn() });

    expect(prompts.cancel).toHaveBeenCalledWith("Launcher cancelled.");
    expect(Object.values(actions).every(action => action.mock.calls.length === 0)).toBe(true);
  });
});
