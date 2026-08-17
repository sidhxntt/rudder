import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import WorkspacePage from "./workspace-page";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/session", () => ({
  useSession: () => ({
    state: {
      status: "authenticated",
      user: {
        id: "user-1",
        email: "maya@example.com",
        github_login: "maya",
        github_avatar_url: null,
        created_at: "2026-08-01T00:00:00Z",
      },
    },
  }),
}));

vi.mock("@/lib/queries", () => ({
  useProjects: () => ({
    data: [
      { id: "project-1", name: "checkout", owner_id: "user-1", created_at: "2026-08-16T10:00:00Z" },
      { id: "project-2", name: "docs", owner_id: "user-1", created_at: "2026-08-15T10:00:00Z" },
    ],
    isPending: false,
    isError: false,
    isSuccess: true,
    refetch: vi.fn(),
  }),
  useNodes: () => ({
    data: [
      {
        id: "node-1",
        hostname: "runner-01",
        ip_address: "10.0.0.8",
        status: "healthy",
        last_heartbeat_at: "2026-08-16T12:00:00Z",
        instances: [],
      },
      {
        id: "node-2",
        hostname: "runner-02",
        ip_address: "10.0.0.9",
        status: "unreachable",
        last_heartbeat_at: null,
        instances: [],
      },
    ],
    isPending: false,
    isError: false,
    isSuccess: true,
    refetch: vi.fn(),
  }),
}));

vi.mock("./projects/[projectId]/environments/[environmentId]/github-import-dialog", () => ({
  GitHubImportDialog: ({ triggerLabel }: { triggerLabel: string }) => <button type="button">{triggerLabel}</button>,
}));

it("turns live workspace data into a scannable operator overview and inventory", () => {
  render(<WorkspacePage />);

  expect(screen.getByRole("heading", { name: "Workspace overview" })).toBeTruthy();
  expect(screen.getByText("2 projects")).toBeTruthy();
  expect(screen.getByText("1 healthy node")).toBeTruthy();
  expect(screen.getByRole("heading", { name: "Project inventory" })).toBeTruthy();
  expect(screen.getByRole("link", { name: /open checkout project/i }).getAttribute("href")).toBe("/projects/project-1");
  expect(screen.getByRole("heading", { name: "Fleet" })).toBeTruthy();
  expect(screen.getByText("runner-02")).toBeTruthy();
});
