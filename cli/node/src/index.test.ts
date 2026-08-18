import { afterEach, describe, expect, it, vi } from "vitest";
import { mkdtempSync, mkdirSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

const launcher = vi.hoisted(() => ({ runLauncher: vi.fn() }));
const context = vi.hoisted(() => ({
  loadConfig: vi.fn().mockResolvedValue({ context: {}, credentials: {} }),
  mergeContext: vi.fn(() => ({})),
  saveConfig: vi.fn(),
}));
const prompts = vi.hoisted(() => ({
  isCancel: vi.fn(() => false),
  select: vi.fn(),
}));
const importWizard = vi.hoisted(() => ({ runGitHubImportWizard: vi.fn() }));

vi.mock("./launcher.js", async importOriginal => ({ ...await importOriginal<typeof import("./launcher.js")>(), runLauncher: launcher.runLauncher }));
vi.mock("./context.js", async importOriginal => ({ ...await importOriginal<typeof import("./context.js")>(), ...context }));
vi.mock("@clack/prompts", () => prompts);
vi.mock("./github-import-wizard.js", () => importWizard);

import { chooseInitialProject, chooseProjectEnvironment, discardSession, isDirectExecution, main } from "./index.js";
import { ApiClient } from "./client.js";

const stdinTTY = Object.getOwnPropertyDescriptor(process.stdin, "isTTY");
const stdoutTTY = Object.getOwnPropertyDescriptor(process.stdout, "isTTY");
const argv = process.argv;

afterEach(() => {
  process.argv = argv;
  if (stdinTTY) Object.defineProperty(process.stdin, "isTTY", stdinTTY); else delete (process.stdin as { isTTY?: boolean }).isTTY;
  if (stdoutTTY) Object.defineProperty(process.stdout, "isTTY", stdoutTTY); else delete (process.stdout as { isTTY?: boolean }).isTTY;
  vi.restoreAllMocks();
  prompts.select.mockReset();
  prompts.isCancel.mockReset().mockReturnValue(false);
  launcher.runLauncher.mockReset();
  context.saveConfig.mockReset();
  importWizard.runGitHubImportWizard.mockReset();
});

describe("main", () => {
  it("recognizes a symlinked bin as the direct executable", () => {
    const directory = mkdtempSync(join(tmpdir(), "rudder-cli-"));
    const moduleFile = join(directory, "package", "dist", "index.js");
    const bin = join(directory, "bin", "rudder");
    mkdirSync(join(directory, "package", "dist"), { recursive: true });
    mkdirSync(join(directory, "bin"), { recursive: true });
    writeFileSync(moduleFile, "");
    symlinkSync(moduleFile, bin);
    try {
      expect(isDirectExecution(bin, moduleFile)).toBe(true);
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  });

  it("prints usage instead of launching when stdout is redirected", async () => {
    context.loadConfig.mockResolvedValue({ context: {}, credentials: {} });
    context.mergeContext.mockReturnValue({});
    process.argv = ["node", "rudder"];
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: true });
    Object.defineProperty(process.stdout, "isTTY", { configurable: true, value: false });
    const log = vi.spyOn(console, "log").mockImplementation(() => undefined);

    await main();

    expect(launcher.runLauncher).not.toHaveBeenCalled();
    expect(log).toHaveBeenCalledWith(expect.stringContaining("Usage: rudder"));
  });

  it("removes the old bearer token before any later protected request", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    const session = { api: new ApiClient("https://cp.example", "old-token"), credentials: { token: "old-token" } };

    discardSession(session);
    await session.api.request("GET", "/protected");

    expect(session.credentials.token).toBeUndefined();
    expect(fetcher).toHaveBeenCalledWith("https://cp.example/protected", expect.objectContaining({ headers: expect.not.objectContaining({ authorization: "Bearer old-token" }) }));
  });

  it("uses the web's development label for a local production environment", async () => {
    prompts.select.mockResolvedValueOnce("project-id").mockResolvedValueOnce("environment-id");
    const api = { baseUrl: "http://localhost:8000", request: vi.fn().mockResolvedValueOnce([{ id: "project-id", name: "API" }]).mockResolvedValueOnce([{ id: "environment-id", name: "production", is_production: true }]) };
    const state = { api, context: {}, credentials: { url: "http://localhost:8000" }, flags: {}, out: { json: false } };

    await expect(chooseProjectEnvironment(state as never)).resolves.toBe("Using API / development");

    expect(state.context).toEqual({ project: "project-id", environment: "environment-id" });
    expect(context.saveConfig).toHaveBeenCalledWith(state.context, state.credentials);
    expect(api.request).toHaveBeenNthCalledWith(1, "GET", "/projects");
    expect(api.request).toHaveBeenNthCalledWith(2, "GET", "/projects/project-id/environments");
  });

  it("sets the initial context from an existing project before the launcher can open", async () => {
    prompts.select.mockResolvedValueOnce("project-id");
    const api = {
      baseUrl: "http://localhost:8000",
      request: vi.fn()
        .mockResolvedValueOnce([{ id: "project-id", name: "API" }])
        .mockResolvedValueOnce([{ id: "environment-id", name: "production", is_production: true }]),
    };
    const state = { api, context: {}, credentials: {}, flags: {}, out: { json: false } };

    await expect(chooseInitialProject(state as never)).resolves.toBe("Using API / development");

    expect(state.context).toEqual({ project: "project-id", environment: "environment-id" });
    expect(context.saveConfig).toHaveBeenCalledWith(state.context, state.credentials);
  });

  it("shows the most recently created projects first, matching the web workspace", async () => {
    prompts.select.mockResolvedValueOnce(Symbol.for("cancel"));
    prompts.isCancel.mockReturnValue(true);
    const api = {
      baseUrl: "http://localhost:8000",
      request: vi.fn().mockResolvedValueOnce([
        { id: "older", name: "older project", created_at: "2026-08-01T00:00:00Z" },
        { id: "newer", name: "newer project", created_at: "2026-08-18T00:00:00Z" },
      ]),
    };
    const state = { api, context: {}, credentials: {}, flags: {}, out: { json: false } };

    await expect(chooseInitialProject(state as never)).resolves.toBeUndefined();

    expect(prompts.select).toHaveBeenCalledWith(expect.objectContaining({
      options: expect.arrayContaining([
        expect.objectContaining({ value: "newer" }),
        expect.objectContaining({ value: "older" }),
      ]),
    }));
    const options = prompts.select.mock.calls[0]![0].options as Array<{ value: string }>;
    expect(options.slice(0, 2).map(option => option.value)).toEqual(["newer", "older"]);
  });

  it("uses the GitHub wizard when the operator creates a project", async () => {
    prompts.select.mockResolvedValueOnce("create-from-github");
    importWizard.runGitHubImportWizard.mockResolvedValue({ projectId: "project-id", environmentId: "environment-id" });
    const api = { baseUrl: "http://localhost:8000", request: vi.fn().mockResolvedValueOnce([]) };
    const state = { api, context: {}, credentials: {}, flags: {}, out: { json: false } };

    await expect(chooseInitialProject(state as never)).resolves.toBe("Project created from GitHub.");

    expect(importWizard.runGitHubImportWizard).toHaveBeenCalledWith({ api });
    expect(state.context).toEqual({ project: "project-id", environment: "environment-id" });
    expect(context.saveConfig).toHaveBeenCalledWith(state.context, state.credentials);
  });

  it("requires project onboarding after a new GitHub sign-in even when old context remains", async () => {
    context.loadConfig.mockResolvedValue({
      context: { project: "old-project", environment: "old-environment" },
      credentials: {},
    });
    context.mergeContext.mockReturnValue({ project: "old-project", environment: "old-environment" });
    process.argv = ["node", "rudder"];
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: true });
    Object.defineProperty(process.stdout, "isTTY", { configurable: true, value: true });

    await main();

    expect(launcher.runLauncher).toHaveBeenCalledWith(expect.objectContaining({
      authenticated: false,
      projectSelected: false,
    }));
  });
});
