import { describe, expect, it, vi } from "vitest";

import { runGitHubImportWizard } from "./github-import-wizard.js";
import { CliCancellationError } from "./errors.js";

const cancelled = Symbol.for("cancel");

describe("runGitHubImportWizard", () => {
  it("uses the same reviewed GitHub import flow as the web and returns its context", async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ configured: true, message: "ready" })
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([{ id: 7, account_login: "acme", repository_selection: "all" }])
      .mockResolvedValueOnce([{ full_name: "acme/api", default_branch: "main", private: true }])
      .mockResolvedValueOnce(["main"])
      .mockResolvedValueOnce({ compose_source: "generated", addons: ["postgres"], services: [{ name: "app", role: "web", is_public: true }] })
      .mockResolvedValueOnce({ import_id: "import", project_id: "project", environment_id: "environment", app_service_id: "app" })
      .mockResolvedValueOnce({ steps: [{ service_name: "app", status: "queued", error_message: null }] });
    const spinner = { start: vi.fn(), stop: vi.fn() };
    const prompts = {
      select: vi.fn()
        .mockResolvedValueOnce("repository")
        .mockResolvedValueOnce(7)
        .mockResolvedValueOnce("acme/api")
        .mockResolvedValueOnce("main"),
      multiselect: vi.fn().mockResolvedValueOnce(["postgres"]).mockResolvedValueOnce(["app"]),
      confirm: vi.fn().mockResolvedValue(true),
      isCancel: vi.fn((value: unknown) => value === cancelled),
      note: vi.fn(),
      spinner: vi.fn(() => spinner),
    };

    await expect(runGitHubImportWizard({ api: { request }, prompts: prompts as never })).resolves.toEqual({
      projectId: "project",
      environmentId: "environment",
    });

    expect(request).toHaveBeenNthCalledWith(1, "GET", "/github/import/status");
    expect(request).toHaveBeenNthCalledWith(6, "POST", "/github/import/preview", {
      installation_id: 7, repository: "acme/api", branch: "main", template_id: null,
    });
    expect(request).toHaveBeenNthCalledWith(7, "POST", "/github/imports", {
      installation_id: 7,
      repository: "acme/api",
      branch: "main",
      template_id: null,
      addons: ["postgres"],
      public_services: ["app"],
    });
    expect(spinner.start).toHaveBeenCalledWith("Inspecting acme/api@main");
    expect(spinner.stop).toHaveBeenCalledWith("Release created");
    expect(prompts.note).toHaveBeenCalledWith(
      "app · queued\n\nOpen in web: http://localhost:3000/projects/project/environments/environment",
      "Import started",
    );
  });

  it("returns without creating a project when confirmation is declined", async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ configured: true, message: "ready" })
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([{ id: 7, account_login: "acme", repository_selection: "all" }])
      .mockResolvedValueOnce([{ full_name: "acme/api", default_branch: "main", private: true }])
      .mockResolvedValueOnce(["main"])
      .mockResolvedValueOnce({ compose_source: "repository", addons: [], services: [{ name: "app", role: "web", is_public: true }] });
    const prompts = {
      select: vi.fn().mockResolvedValueOnce("repository").mockResolvedValueOnce(7).mockResolvedValueOnce("acme/api").mockResolvedValueOnce("main"),
      multiselect: vi.fn().mockResolvedValueOnce(["app"]),
      confirm: vi.fn().mockResolvedValue(false),
      isCancel: vi.fn((value: unknown) => value === cancelled),
      note: vi.fn(),
      spinner: vi.fn(() => ({ start: vi.fn(), stop: vi.fn() })),
    };

    await expect(runGitHubImportWizard({ api: { request }, prompts: prompts as never })).resolves.toBeUndefined();
    expect(request).not.toHaveBeenCalledWith("POST", "/github/imports", expect.anything());
  });

  it.each([
    ["source", 0],
    ["GitHub connection", 1],
    ["repository", 2],
    ["branch", 3],
  ])("turns cancellation at %s into a CLI cancellation", async (_stage, cancelAt) => {
    const request = vi.fn()
      .mockResolvedValueOnce({ configured: true })
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([{ id: 7, account_login: "acme", repository_selection: "all" }])
      .mockResolvedValueOnce([{ full_name: "acme/api", default_branch: "main", private: true }])
      .mockResolvedValueOnce(["main"]);
    const spinner = { start: vi.fn(), stop: vi.fn() };
    const selections = ["repository", 7, "acme/api", "main"];
    selections[cancelAt] = cancelled as never;
    const prompts = {
      select: vi.fn().mockImplementation(() => Promise.resolve(selections.shift())),
      multiselect: vi.fn(), confirm: vi.fn(),
      isCancel: vi.fn((value: unknown) => value === cancelled), note: vi.fn(), spinner: vi.fn(() => spinner),
    };

    await expect(runGitHubImportWizard({ api: { request }, prompts: prompts as never })).rejects.toBeInstanceOf(CliCancellationError);
    expect(request).not.toHaveBeenCalledWith("POST", "/github/imports", expect.anything());
  });

  it.each(["private add-ons", "public services"])("turns cancellation at %s into a CLI cancellation", async stage => {
    const request = vi.fn()
      .mockResolvedValueOnce({ configured: true })
      .mockResolvedValueOnce([])
      .mockResolvedValueOnce([{ id: 7, account_login: "acme", repository_selection: "all" }])
      .mockResolvedValueOnce([{ full_name: "acme/api", default_branch: "main", private: true }])
      .mockResolvedValueOnce(["main"])
      .mockResolvedValueOnce({ compose_source: "generated", addons: ["postgres"], services: [{ name: "app", role: "web", is_public: true }] });
    const multiselect = vi.fn()
      .mockResolvedValueOnce(stage === "private add-ons" ? cancelled : ["postgres"])
      .mockResolvedValueOnce(stage === "public services" ? cancelled : ["app"]);
    const prompts = {
      select: vi.fn().mockResolvedValueOnce("repository").mockResolvedValueOnce(7).mockResolvedValueOnce("acme/api").mockResolvedValueOnce("main"),
      multiselect, confirm: vi.fn(), isCancel: vi.fn((value: unknown) => value === cancelled), note: vi.fn(),
      spinner: vi.fn(() => ({ start: vi.fn(), stop: vi.fn() })),
    };

    await expect(runGitHubImportWizard({ api: { request }, prompts: prompts as never })).rejects.toBeInstanceOf(CliCancellationError);
    expect(request).not.toHaveBeenCalledWith("POST", "/github/imports", expect.anything());
  });
});
