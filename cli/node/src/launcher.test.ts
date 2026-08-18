import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const prompts = vi.hoisted(() => ({
  cancel: vi.fn(),
  intro: vi.fn(),
  isCancel: vi.fn((value: unknown) => value === Symbol.for("cancel")),
  note: vi.fn(),
  outro: vi.fn(),
  select: vi.fn(),
  spinner: vi.fn(),
}));

vi.mock("@clack/prompts", () => prompts);

import { canLaunchLauncher, renderSplash, runLauncher, runStatusMenu } from "./launcher.js";
import { discardSession } from "./index.js";
import { ApiClient } from "./client.js";

beforeEach(() => {
  prompts.cancel.mockReset();
  prompts.intro.mockReset();
  prompts.isCancel.mockReset().mockImplementation((value: unknown) => value === Symbol.for("cancel"));
  prompts.note.mockReset();
  prompts.outro.mockReset();
  prompts.select.mockReset();
  prompts.spinner.mockReset();
});
afterEach(() => vi.unstubAllGlobals());

describe("runLauncher", () => {
  it("offers compact, detailed, AI summary, and Back in the Status submenu", async () => {
    const spinner = { start: vi.fn(), stop: vi.fn() };
    prompts.spinner.mockReturnValue(spinner);
    prompts.select.mockResolvedValueOnce("compact").mockResolvedValueOnce("back");
    const actions = { compact: vi.fn(), detailed: vi.fn(), summary: vi.fn() };

    await runStatusMenu(actions);

    expect(prompts.select).toHaveBeenCalledWith(expect.objectContaining({
      message: "Status view",
      options: expect.arrayContaining([
        expect.objectContaining({ value: "compact", label: "Compact status" }),
        expect.objectContaining({ value: "detailed", label: "Detailed status" }),
        expect.objectContaining({ value: "summary", label: "AI summary" }),
        expect.objectContaining({ value: "back", label: "Back to main menu" }),
      ]),
    }));
    expect(actions.compact).toHaveBeenCalledOnce();
    expect(actions.detailed).not.toHaveBeenCalled();
    expect(actions.summary).not.toHaveBeenCalled();
  });

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

  it("requires project onboarding before showing the operational menu", async () => {
    prompts.select.mockResolvedValueOnce("exit");
    const actions = { signIn: vi.fn(), chooseProject: vi.fn().mockResolvedValue("Using API / development"), chooseTarget: vi.fn(), deploy: vi.fn(), status: vi.fn(), logs: vi.fn(), services: vi.fn(), variables: vi.fn(), advisor: vi.fn(), signOut: vi.fn() };

    await runLauncher({ actions, authenticated: true, projectSelected: false, clear: vi.fn() });

    expect(actions.chooseProject).toHaveBeenCalledOnce();
    expect(prompts.select).toHaveBeenNthCalledWith(1, expect.objectContaining({ message: "What would you like to do?" }));
  });

  it("offers Back to project selection instead of a project/environment action", async () => {
    prompts.select.mockResolvedValueOnce("back").mockResolvedValueOnce("exit");
    const actions = { signIn: vi.fn(), chooseProject: vi.fn().mockResolvedValue("Using current / development"), chooseTarget: vi.fn(), deploy: vi.fn(), status: vi.fn(), logs: vi.fn(), services: vi.fn(), variables: vi.fn(), advisor: vi.fn(), signOut: vi.fn() };

    await runLauncher({ actions, authenticated: true, clear: vi.fn() });

    const options = prompts.select.mock.calls[0]![0].options as Array<{ value: string; label: string }>;
    expect(options.map(option => option.value)).not.toContain("choose-target");
    expect(options).toContainEqual(expect.objectContaining({ value: "back", label: "Back to project selection" }));
    expect(options.findIndex(option => option.value === "back")).toBeLessThan(options.findIndex(option => option.value === "exit"));
    expect(actions.chooseProject).toHaveBeenCalledOnce();
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
