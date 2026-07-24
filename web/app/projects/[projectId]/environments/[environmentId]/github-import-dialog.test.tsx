import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hooks = vi.hoisted(() => ({
  confirm: { isPending: false, isError: false, mutateAsync: vi.fn() },
  status: { data: { configured: true, install_url: null }, isLoading: false, isError: false },
  templates: { data: [{ id: "node-web", name: "Node web service", description: "A web app", addons: [] }] },
  installations: {
    data: [{ id: 7, account_login: "acme", repository_selection: "all" }],
    isLoading: false,
    isError: false,
  },
  repositories: {
    data: [{ full_name: "acme/api", default_branch: "main", private: true }],
    isLoading: false,
    isError: false,
  },
  branches: { data: ["main"] },
  imported: { data: undefined, isError: false },
  preview: {
    data: {
      is_node_app: true,
      addons: ["postgres"],
      externally_managed: [],
      compose_source: "generated" as const,
      compose_manifest: "services:\n  app: {}\n  postgres: {}\n  grafana: {}",
      services: [
        { name: "app", role: "web", public_port: 3000, container_port: 3000, is_public: true },
        { name: "postgres", role: "database", public_port: null, container_port: 5432, is_public: false },
        { name: "grafana", role: "observability", public_port: 3000, container_port: 3000, is_public: true },
      ],
      processes: [{ role: "worker" as const, command: "npm run worker", source: "package_json" as const }],
    },
    isLoading: false,
    isError: false,
  },
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/queries", () => ({
  useConfirmGitHubImport: () => hooks.confirm,
  useGitHubBranches: () => hooks.branches,
  useGitHubImport: () => hooks.imported,
  useGitHubImportPreview: () => hooks.preview,
  useGitHubImportStatus: () => hooks.status,
  useGitHubImportTemplates: () => hooks.templates,
  useGitHubInstallations: () => hooks.installations,
  useGitHubRepositories: () => hooks.repositories,
}));

import { GitHubImportDialog } from "./github-import-dialog";

describe("GitHubImportDialog", () => {
  beforeEach(() => {
    hooks.confirm.mutateAsync.mockReset();
  });

  it("guides a repository import through source, repository, review, and release confirmation", async () => {
    const user = userEvent.setup();
    render(<GitHubImportDialog />);

    await user.click(screen.getByRole("button", { name: "Import from GitHub" }));
    expect(screen.getByText("Step 1 of 4")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Choose a source" })).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Next: repository" }));
    expect(screen.getByText("Step 2 of 4")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Select repository" })).toBeTruthy();

    await user.click(screen.getByRole("button", { name: "Next: review services" }));
    expect(screen.getByText("Step 3 of 4")).toBeTruthy();
    expect(screen.getByText("Detected processes")).toBeTruthy();
    expect(screen.getByText("npm run worker")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Next: release summary" }));
    const publicServiceChecks = screen.getAllByRole("checkbox", { name: "Public" });
    expect((publicServiceChecks[0] as HTMLInputElement).checked).toBe(true);
    expect((publicServiceChecks[1] as HTMLInputElement).checked).toBe(false);
    await user.click(publicServiceChecks[1]);

    expect(screen.getByText("Step 4 of 4")).toBeTruthy();
    expect(screen.getByText("Public URLs")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Confirm and deploy" }).hasAttribute("disabled")).toBe(false);
  });
});
