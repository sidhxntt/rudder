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
  cancel: vi.fn(),
  isCancel: vi.fn(() => false),
  select: vi.fn(),
}));
const importWizard = vi.hoisted(() => ({ runGitHubImportWizard: vi.fn() }));

vi.mock("./launcher.js", async importOriginal => ({ ...await importOriginal<typeof import("./launcher.js")>(), runLauncher: launcher.runLauncher }));
vi.mock("./context.js", async importOriginal => ({ ...await importOriginal<typeof import("./context.js")>(), ...context }));
vi.mock("@clack/prompts", () => prompts);
vi.mock("./github-import-wizard.js", () => importWizard);

import { CliCancellationError, CliUsageError, chooseInitialProject, chooseProjectEnvironment, chooseServiceForLogs, discardSession, exitCodeForError, isDirectExecution, main, parseArgs, renderCliError, toErrorEnvelope } from "./index.js";
import { ApiClient } from "./client.js";

const stdinTTY = Object.getOwnPropertyDescriptor(process.stdin, "isTTY");
const stdoutTTY = Object.getOwnPropertyDescriptor(process.stdout, "isTTY");
const argv = process.argv;

afterEach(() => {
  process.argv = argv;
  if (stdinTTY) Object.defineProperty(process.stdin, "isTTY", stdinTTY); else delete (process.stdin as { isTTY?: boolean }).isTTY;
  if (stdoutTTY) Object.defineProperty(process.stdout, "isTTY", stdoutTTY); else delete (process.stdout as { isTTY?: boolean }).isTTY;
  vi.restoreAllMocks();
  vi.useRealTimers();
  prompts.select.mockReset();
  prompts.cancel.mockReset();
  prompts.isCancel.mockReset().mockReturnValue(false);
  launcher.runLauncher.mockReset();
  context.saveConfig.mockReset();
  importWizard.runGitHubImportWizard.mockReset();
});

describe("main", () => {
  it("keeps known boolean flags from consuming a command token in any position", () => {
    expect(parseArgs(["--json", "status", "--follow", "--build", "--no-interactive"])).toEqual({
      args: ["status"],
      flags: { json: true, follow: true, build: true, "no-interactive": true },
    });
    expect(parseArgs(["status", "--json", "--runtime", "--yes"])).toEqual({
      args: ["status"],
      flags: { json: true, runtime: true, yes: true },
    });
  });

  it("maps usage and cancellation to the documented process statuses", () => {
    expect(exitCodeForError(new CliUsageError("Missing service."))).toBe(2);
    expect(exitCodeForError(new CliCancellationError())).toBe(130);
    expect(exitCodeForError(new Error("network failed"))).toBe(1);
  });

  it("serializes every JSON-mode error as one parseable envelope", () => {
    expect(toErrorEnvelope(new CliUsageError("Missing service."))).toEqual({
      code: "usage",
      message: "Missing service.",
      details: {},
    });
  });

  it("writes exactly one JSON error envelope in JSON mode", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => undefined);

    renderCliError(new CliUsageError("Missing command."), true);

    expect(error).toHaveBeenCalledOnce();
    expect(JSON.parse(error.mock.calls[0]![0] as string)).toEqual({ code: "usage", message: "Missing command.", details: {} });
  });

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

  it.each(["project picker", "environment picker"])("treats cancelling the %s as a CLI cancellation", async (picker) => {
    const cancelled = Symbol.for("cancel");
    prompts.isCancel.mockImplementation(((value: unknown) => value === cancelled) as never);
    prompts.select.mockResolvedValueOnce(picker === "project picker" ? cancelled : "project-id").mockResolvedValueOnce(cancelled);
    const api = {
      baseUrl: "http://localhost:8000",
      request: vi.fn()
        .mockResolvedValueOnce([{ id: "project-id", name: "API" }])
        .mockResolvedValueOnce([{ id: "environment-id", name: "production" }]),
    };
    const state = { api, context: {}, credentials: {}, flags: {}, out: { json: false } };

    await expect(chooseProjectEnvironment(state as never)).rejects.toBeInstanceOf(CliCancellationError);
    expect(exitCodeForError(new CliCancellationError())).toBe(130);
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

    await expect(chooseInitialProject(state as never)).rejects.toBeInstanceOf(CliCancellationError);

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

  it("prints compact status instead of a raw API payload outside the launcher", async () => {
    context.loadConfig.mockResolvedValue({
      context: { project: "00000000-0000-4000-8000-000000000001", environment: "00000000-0000-4000-8000-000000000002" },
      credentials: { token: "token" },
    });
    context.mergeContext.mockReturnValue({ project: "00000000-0000-4000-8000-000000000001", environment: "00000000-0000-4000-8000-000000000002" });
    process.argv = ["node", "rudder", "status", "--no-interactive"];
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: false });
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "service-id", name: "app" }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "deployment-id", status: "live", commit_sha: "106b06e83c903352050942790f1b8569d9de62f7" }]), { status: 200 }))
      .mockResolvedValueOnce(new Response(JSON.stringify([{ deployment_id: "deployment-id", status: "healthy" }]), { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    const log = vi.spyOn(console, "log").mockImplementation(() => undefined);

    await main();

    expect(log).toHaveBeenCalledWith(expect.stringContaining("Rudder status · 1 service"));
    expect(log).toHaveBeenCalledWith(expect.stringContaining("1/1 release containers healthy"));
  });

  it("treats JSON mode as non-interactive before authentication", async () => {
    context.loadConfig.mockResolvedValue({ context: {}, credentials: {} });
    context.mergeContext.mockReturnValue({});
    process.argv = ["node", "rudder", "--json", "status"];
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: true });
    Object.defineProperty(process.stdout, "isTTY", { configurable: true, value: true });

    await expect(main()).rejects.toMatchObject({ message: expect.stringContaining("RUDDER_TOKEN") });
  });

  it("routes build logs to the selected deployment even when following", async () => {
    context.loadConfig.mockResolvedValue({
      context: { project: "00000000-0000-4000-8000-000000000001", environment: "00000000-0000-4000-8000-000000000002", service: "00000000-0000-4000-8000-000000000003" },
      credentials: { token: "token" },
    });
    context.mergeContext.mockReturnValue({ project: "00000000-0000-4000-8000-000000000001", environment: "00000000-0000-4000-8000-000000000002", service: "00000000-0000-4000-8000-000000000003" });
    process.argv = ["node", "rudder", "logs", "--build", "--follow", "--no-interactive"];
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: false });
    const fetcher = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify([{ id: "deployment-id" }]), { status: 200 }))
      .mockResolvedValueOnce(new Response("data: build line\n\n", { status: 200 }));
    vi.stubGlobal("fetch", fetcher);

    await main();

    expect(fetcher).toHaveBeenLastCalledWith("http://localhost:8000/deployments/deployment-id/build-log?follow=true", expect.anything());
  });

  it("routes runtime logs to the service when explicitly requested with follow", async () => {
    context.loadConfig.mockResolvedValue({
      context: { project: "00000000-0000-4000-8000-000000000001", environment: "00000000-0000-4000-8000-000000000002", service: "00000000-0000-4000-8000-000000000003" },
      credentials: { token: "token" },
    });
    context.mergeContext.mockReturnValue({ project: "00000000-0000-4000-8000-000000000001", environment: "00000000-0000-4000-8000-000000000002", service: "00000000-0000-4000-8000-000000000003" });
    process.argv = ["node", "rudder", "logs", "--runtime", "--follow", "--no-interactive"];
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: false });
    const fetcher = vi.fn().mockResolvedValueOnce(new Response("data: runtime line\n\n", { status: 200 }));
    vi.stubGlobal("fetch", fetcher);

    await main();

    expect(fetcher).toHaveBeenLastCalledWith("http://localhost:8000/services/00000000-0000-4000-8000-000000000003/runtime-log?follow=true", expect.anything());
  });

  it("uses the follow contract and emits structured JSON Lines for runtime logs", async () => {
    context.loadConfig.mockResolvedValue({
      context: { project: "00000000-0000-4000-8000-000000000001", environment: "00000000-0000-4000-8000-000000000002", service: "00000000-0000-4000-8000-000000000003" },
      credentials: { token: "token" },
    });
    context.mergeContext.mockReturnValue({ project: "00000000-0000-4000-8000-000000000001", environment: "00000000-0000-4000-8000-000000000002", service: "00000000-0000-4000-8000-000000000003" });
    process.argv = ["node", "rudder", "logs", "--runtime", "--follow", "--json"];
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: false });
    vi.setSystemTime(new Date("2026-08-18T09:00:00.000Z"));
    const fetcher = vi.fn().mockResolvedValueOnce(new Response("data: [ERROR] database unavailable\n\n", { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    const log = vi.spyOn(console, "log").mockImplementation(() => undefined);

    await main();

    expect(fetcher).toHaveBeenLastCalledWith("http://localhost:8000/services/00000000-0000-4000-8000-000000000003/runtime-log?follow=true", expect.anything());
    expect(log.mock.calls.map(([line]) => JSON.parse(line as string))).toEqual([{
      timestamp: "2026-08-18T09:00:00.000Z", source: "runtime", level: "error", message: "[ERROR] database unavailable",
    }]);
  });

  it("rejects an ambiguous service name with the matching identifiers", async () => {
    context.loadConfig.mockResolvedValue({
      context: { project: "00000000-0000-4000-8000-000000000001", environment: "00000000-0000-4000-8000-000000000002" },
      credentials: { token: "token" },
    });
    context.mergeContext.mockReturnValue({ project: "00000000-0000-4000-8000-000000000001", environment: "00000000-0000-4000-8000-000000000002" });
    process.argv = ["node", "rudder", "logs", "app", "--runtime", "--no-interactive"];
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: false });
    const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify([
      { id: "service-a", name: "app" }, { id: "service-b", name: "app" },
    ]), { status: 200 }));
    vi.stubGlobal("fetch", fetcher);

    await expect(main()).rejects.toThrow("Service name app is ambiguous; use one of: service-a, service-b.");
  });

  it("rejects selecting both log sources as usage", async () => {
    context.loadConfig.mockResolvedValue({
      context: { project: "00000000-0000-4000-8000-000000000001", environment: "00000000-0000-4000-8000-000000000002", service: "00000000-0000-4000-8000-000000000003" },
      credentials: { token: "token" },
    });
    context.mergeContext.mockReturnValue({ project: "00000000-0000-4000-8000-000000000001", environment: "00000000-0000-4000-8000-000000000002", service: "00000000-0000-4000-8000-000000000003" });
    process.argv = ["node", "rudder", "logs", "--build", "--runtime", "--no-interactive"];
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: false });

    await expect(main()).rejects.toBeInstanceOf(CliUsageError);
  });

  it("classifies an unknown command as usage", async () => {
    context.loadConfig.mockResolvedValue({ context: {}, credentials: { token: "token" } });
    context.mergeContext.mockReturnValue({});
    process.argv = ["node", "rudder", "wat", "--no-interactive"];
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: false });

    await expect(main()).rejects.toBeInstanceOf(CliUsageError);
  });

  it.each([
    ["rollback", "missing rollback id"],
    ["project unsupported", "invalid resource subcommand"],
    ["var set FEATURE_FLAG", "missing variable value"],
    ["advisor accept", "invalid advisor arguments"],
  ])("classifies %s as usage (%s)", async (commandLine) => {
    context.loadConfig.mockResolvedValue({
      context: {
        project: "00000000-0000-4000-8000-000000000001",
        environment: "00000000-0000-4000-8000-000000000002",
        service: "00000000-0000-4000-8000-000000000003",
      },
      credentials: { token: "token" },
    });
    context.mergeContext.mockReturnValue({
      project: "00000000-0000-4000-8000-000000000001",
      environment: "00000000-0000-4000-8000-000000000002",
      service: "00000000-0000-4000-8000-000000000003",
    });
    process.argv = ["node", "rudder", ...commandLine.split(" "), "--no-interactive"];
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: false });

    await expect(main()).rejects.toBeInstanceOf(CliUsageError);
  });

  it("asks for a service before opening logs when none is selected", async () => {
    prompts.select.mockResolvedValueOnce("service-id");
    const api = {
      baseUrl: "http://localhost:8000",
      request: vi.fn().mockResolvedValueOnce([
        { id: "service-id", name: "app" },
        { id: "database-id", name: "postgres" },
      ]),
    };
    const state = {
      api,
      context: { project: "00000000-0000-4000-8000-000000000001", environment: "00000000-0000-4000-8000-000000000002" },
      credentials: {},
      flags: {},
      out: { json: false },
    };

    await expect(chooseServiceForLogs(state as never)).resolves.toBe("service-id");

    expect(prompts.select).toHaveBeenCalledWith(expect.objectContaining({ message: "Choose a service for logs" }));
    expect((state.context as { service?: string }).service).toBe("service-id");
    expect(context.saveConfig).toHaveBeenCalledWith(state.context, state.credentials);
  });

  it("treats cancelling the service picker as a CLI cancellation", async () => {
    const cancelled = Symbol.for("cancel");
    prompts.select.mockResolvedValueOnce(cancelled);
    prompts.isCancel.mockReturnValue(true);
    const api = {
      baseUrl: "http://localhost:8000",
      request: vi.fn().mockResolvedValueOnce([{ id: "service-id", name: "app" }]),
    };
    const state = {
      api,
      context: { project: "00000000-0000-4000-8000-000000000001", environment: "00000000-0000-4000-8000-000000000002" },
      credentials: {}, flags: {}, out: { json: false },
    };

    await expect(chooseServiceForLogs(state as never)).rejects.toBeInstanceOf(CliCancellationError);
    expect(exitCodeForError(new CliCancellationError())).toBe(130);
  });

  it("keeps explicit project-picker exit as a successful return", async () => {
    prompts.select.mockResolvedValueOnce("exit");
    const api = { baseUrl: "http://localhost:8000", request: vi.fn().mockResolvedValueOnce([]) };
    const state = { api, context: {}, credentials: {}, flags: {}, out: { json: false } };

    await expect(chooseInitialProject(state as never)).resolves.toBeUndefined();
  });

  it.each([
    [["--wat"], "unknown flag"],
    [["--json=garbage", "status"], "invalid boolean"],
    [["status", "extra"], "status trailing positional"],
    [["context", "unsupported"], "unsupported context action"],
    [["logout", "extra"], "logout trailing positional"],
  ])("rejects %s as usage (%s)", async (argvParts) => {
    context.loadConfig.mockResolvedValue({ context: {}, credentials: { token: "token" } });
    context.mergeContext.mockReturnValue({});
    process.argv = ["node", "rudder", ...argvParts];
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: false });

    await expect(main()).rejects.toBeInstanceOf(CliUsageError);
  });

  it.each([
    [["project", "create", "name", "extra"]], [["project", "get", "project-id", "extra"]],
    [["env", "create", "name", "extra"]], [["env", "clone", "environment-id", "name", "extra"]],
    [["service", "create", "name", "extra"]], [["service", "template", "postgres", "extra"]],
    [["var", "list", "extra"]], [["var", "set", "KEY", "VALUE", "extra"]], [["var", "unset", "KEY", "extra"]],
    [["deploy", "service-id", "extra"]], [["history", "service-id", "extra"]], [["logs", "service-id", "extra"]],
    [["metrics", "service-id", "extra"]], [["rollback", "deployment-id", "extra"]],
    [["operation", "list", "service-id", "extra"]], [["operation", "update", "service-id", "extra"]],
    [["import", "repositories", "installation-id", "extra"]], [["import", "branches", "installation-id", "repository", "extra"]],
    [["import", "get", "import-id", "extra"]], [["domain", "delete", "domain-id", "extra"]],
    [["advisor", "scan", "extra"]], [["advisor", "accept", "extra"]],
  ])("rejects extra positionals for documented command %j", async (argvParts: string[]) => {
    context.loadConfig.mockResolvedValue({
      context: {
        project: "00000000-0000-4000-8000-000000000001",
        environment: "00000000-0000-4000-8000-000000000002",
        service: "00000000-0000-4000-8000-000000000003",
      },
      credentials: { token: "token" },
    });
    context.mergeContext.mockReturnValue({
      project: "00000000-0000-4000-8000-000000000001",
      environment: "00000000-0000-4000-8000-000000000002",
      service: "00000000-0000-4000-8000-000000000003",
    });
    process.argv = ["node", "rudder", ...argvParts, "--no-interactive"];
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: false });
    const fetcher = vi.fn();
    vi.stubGlobal("fetch", fetcher);

    await expect(main()).rejects.toBeInstanceOf(CliUsageError);
    expect(fetcher).not.toHaveBeenCalled();
  });

  it("emits one stream-compatible JSON error record when logs fail after output begins", async () => {
    context.loadConfig.mockResolvedValue({
      context: { project: "00000000-0000-4000-8000-000000000001", environment: "00000000-0000-4000-8000-000000000002", service: "00000000-0000-4000-8000-000000000003" },
      credentials: { token: "token" },
    });
    context.mergeContext.mockReturnValue({ project: "00000000-0000-4000-8000-000000000001", environment: "00000000-0000-4000-8000-000000000002", service: "00000000-0000-4000-8000-000000000003" });
    process.argv = ["node", "rudder", "logs", "--json", "--runtime"];
    let pulls = 0;
    const stream = new ReadableStream<Uint8Array>({
      pull(controller) {
        pulls += 1;
        if (pulls === 1) controller.enqueue(new TextEncoder().encode("data: first line\n\n"));
        else controller.error(new Error("stream disconnected"));
      },
    });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(stream, { status: 200 })));
    const log = vi.spyOn(console, "log").mockImplementation(() => undefined);

    await expect(main()).rejects.toThrow("stream disconnected");

    expect(log.mock.calls.map(([line]) => JSON.parse(line as string))).toEqual([
      expect.objectContaining({ source: "runtime", level: "info", message: "first line" }),
      { error: { code: "runtime_error", message: "stream disconnected", details: {} } },
    ]);
  });
});
