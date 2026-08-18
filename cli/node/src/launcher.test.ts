import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const prompts = vi.hoisted(() => ({
  cancel: vi.fn(),
  intro: vi.fn(),
  isCancel: vi.fn((value: unknown) => value === Symbol.for("cancel")),
  outro: vi.fn(),
  select: vi.fn(),
  spinner: vi.fn(),
}));

vi.mock("@clack/prompts", () => prompts);

import { canLaunchLauncher, renderSplash, runLauncher } from "./launcher.js";
import { discardSession } from "./index.js";
import { ApiClient } from "./client.js";

beforeEach(() => {
  prompts.cancel.mockReset();
  prompts.intro.mockReset();
  prompts.isCancel.mockReset().mockImplementation((value: unknown) => value === Symbol.for("cancel"));
  prompts.outro.mockReset();
  prompts.select.mockReset();
  prompts.spinner.mockReset();
});
afterEach(() => vi.unstubAllGlobals());

describe("runLauncher", () => {
  it("renders a distinct Rudder control-plane splash before prompting", () => {
    const log = vi.spyOn(console, "log").mockImplementation(() => undefined);

    renderSplash();

    expect(log).toHaveBeenCalledWith(expect.stringContaining("RUDDER"));
    expect(log).toHaveBeenCalledWith(expect.stringContaining("DEPLOYMENT CONTROL PLANE"));
    expect(log).toHaveBeenCalledWith(expect.stringContaining("GitHub-authenticated workspace"));
  });

  it("does not launch when stdout is redirected", () => {
    expect(canLaunchLauncher({ hasArgs: false, json: false, noInteractive: false, stdinTTY: true, stdoutTTY: false })).toBe(false);
  });

  it("does not launch when stdin is redirected", () => {
    expect(canLaunchLauncher({ hasArgs: false, json: false, noInteractive: false, stdinTTY: false, stdoutTTY: true })).toBe(false);
  });

  it("clears the terminal and dispatches Deploy through its injected callback", async () => {
    const spinner = { start: vi.fn(), stop: vi.fn() };
    prompts.spinner.mockReturnValue(spinner);
    prompts.select.mockResolvedValueOnce("deploy").mockResolvedValueOnce("exit");
    const actions = { signIn: vi.fn(), chooseTarget: vi.fn(), deploy: vi.fn(), status: vi.fn(), logs: vi.fn(), services: vi.fn(), variables: vi.fn(), advisor: vi.fn(), signOut: vi.fn() };
    const clear = vi.fn();

    await runLauncher({ actions, clear });

    expect(clear).toHaveBeenCalledOnce();
    expect(prompts.intro).toHaveBeenCalledWith("Rudder control plane");
    expect(actions.deploy).toHaveBeenCalledOnce();
    expect(spinner.start).toHaveBeenCalledWith("Deploy");
    expect(prompts.outro).toHaveBeenCalledWith("Until next time.");
  });

  it("shows Sign in with GitHub before the control-plane menu", async () => {
    const spinner = { start: vi.fn(), stop: vi.fn() };
    prompts.spinner.mockReturnValue(spinner);
    prompts.select.mockResolvedValueOnce("sign-in").mockResolvedValueOnce("exit");
    const actions = { signIn: vi.fn(), chooseTarget: vi.fn(), deploy: vi.fn(), status: vi.fn(), logs: vi.fn(), services: vi.fn(), variables: vi.fn(), advisor: vi.fn(), signOut: vi.fn() };

    await runLauncher({ actions, authenticated: false, clear: vi.fn() });

    expect(prompts.select).toHaveBeenNthCalledWith(1, expect.objectContaining({
      message: "Welcome to Rudder",
      options: expect.arrayContaining([expect.objectContaining({ value: "sign-in", label: "Sign in with GitHub" })]),
    }));
    expect(actions.signIn).toHaveBeenCalledOnce();
    expect(prompts.select).toHaveBeenNthCalledWith(2, expect.objectContaining({ message: "What would you like to do?" }));
  });

  it("does not spin while the project/environment picker is awaiting input", async () => {
    const spinner = { start: vi.fn(), stop: vi.fn() };
    prompts.spinner.mockReturnValue(spinner);
    prompts.select.mockResolvedValueOnce("choose-target").mockResolvedValueOnce("exit");
    const actions = { signIn: vi.fn(), chooseTarget: vi.fn().mockResolvedValue("Using api / production"), deploy: vi.fn(), status: vi.fn(), logs: vi.fn(), services: vi.fn(), variables: vi.fn(), advisor: vi.fn(), signOut: vi.fn() };

    await runLauncher({ actions, authenticated: true, clear: vi.fn() });

    expect(actions.chooseTarget).toHaveBeenCalledOnce();
    expect(spinner.start).toHaveBeenCalledWith("Updating context");
    expect(spinner.start).not.toHaveBeenCalledWith("Choose project/environment");
    expect(spinner.stop).toHaveBeenCalledWith("Using api / production");
  });

  it("cancels without invoking an action", async () => {
    prompts.select.mockResolvedValue(Symbol.for("cancel"));
    const actions = { signIn: vi.fn(), chooseTarget: vi.fn(), deploy: vi.fn(), status: vi.fn(), logs: vi.fn(), services: vi.fn(), variables: vi.fn(), advisor: vi.fn(), signOut: vi.fn() };

    await runLauncher({ actions, clear: vi.fn() });

    expect(prompts.cancel).toHaveBeenCalledWith("Launcher cancelled.");
    expect(Object.values(actions).every(action => action.mock.calls.length === 0)).toBe(true);
  });

  it("exits after signing out so a protected action cannot reuse the prior session", async () => {
    const spinner = { start: vi.fn(), stop: vi.fn() };
    prompts.spinner.mockReturnValue(spinner);
    prompts.select.mockResolvedValueOnce("sign-out").mockResolvedValueOnce("deploy");
    const actions = { signIn: vi.fn(), chooseTarget: vi.fn(), deploy: vi.fn(), status: vi.fn(), logs: vi.fn(), services: vi.fn(), variables: vi.fn(), advisor: vi.fn(), signOut: vi.fn() };

    await runLauncher({ actions, clear: vi.fn() });

    expect(actions.signOut).toHaveBeenCalledOnce();
    expect(actions.deploy).not.toHaveBeenCalled();
    expect(prompts.outro).toHaveBeenCalledWith("Signed out.");
  });

  it("does not send the prior bearer after selecting Sign out before a protected action", async () => {
    const spinner = { start: vi.fn(), stop: vi.fn() };
    const fetcher = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    prompts.spinner.mockReturnValue(spinner);
    prompts.select.mockResolvedValueOnce("sign-out").mockResolvedValueOnce("deploy");
    const session = { api: new ApiClient("https://cp.example", "old-token"), credentials: { token: "old-token" } };
    const deploy = vi.fn(async () => { await session.api.request("POST", "/protected"); });
    const actions = { signIn: vi.fn(), chooseTarget: vi.fn(), deploy, status: vi.fn(), logs: vi.fn(), services: vi.fn(), variables: vi.fn(), advisor: vi.fn(), signOut: vi.fn(async () => { discardSession(session); }) };

    await runLauncher({ actions, clear: vi.fn() });

    expect(actions.signOut).toHaveBeenCalledOnce();
    expect(deploy).not.toHaveBeenCalled();
    expect(fetcher).not.toHaveBeenCalled();
  });
});
