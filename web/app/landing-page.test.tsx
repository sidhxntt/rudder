import { render, screen } from "@testing-library/react";
import { beforeAll, expect, it, vi } from "vitest";

import { LandingPage } from "./landing-page";

// The hero runs, parts its planes and pauses off screen with browser APIs jsdom lacks.
beforeAll(() => {
  const observer = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  vi.stubGlobal("ResizeObserver", observer);
  vi.stubGlobal("IntersectionObserver", observer);
  vi.stubGlobal(
    "matchMedia",
    (query: string) =>
      ({ matches: false, media: query, addEventListener() {}, removeEventListener() {} }) as unknown as MediaQueryList,
  );
  vi.stubGlobal("requestAnimationFrame", () => 0);
  vi.stubGlobal("cancelAnimationFrame", () => {});
});

it("opens on the hero: the headline, and the control plane running a release", () => {
  render(<LandingPage authenticated={false} />);

  expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Push the code. Rudder leaves the trail.");
  const plane = screen.getByRole("group", { name: "Rudder control plane, running a sample release" });
  for (const step of ["GitHub push", "Resolve & build", "Healthy?", "Shift traffic", "Mark failed", "Record release"]) {
    expect(plane.textContent).toContain(step);
  }
  expect(screen.getByText("In development")).toBeTruthy();
});

it("gives a signed-out visitor GitHub auth and local-start actions", () => {
  render(<LandingPage authenticated={false} />);

  expect(screen.getByRole("link", { name: "Sign in with GitHub" }).getAttribute("href")).toBe("/api/auth/github/start");
  expect(screen.getAllByRole("link", { name: "Sign in" }).every((link) => link.getAttribute("href") === "/api/auth/github/start")).toBe(true);
  expect(screen.getAllByRole("link", { name: "Run locally" }).every((link) => link.getAttribute("href") === "#run-locally")).toBe(true);
  expect(screen.getByText("GKE controlled beta")).toBeTruthy();
});

it("takes a signed-in visitor to the workspace and the dashboard import flow", () => {
  render(<LandingPage authenticated />);

  expect(screen.getByRole("navigation", { name: "Main" })).toBeTruthy();
  expect(screen.getByRole("link", { name: "Open workspace" }).getAttribute("href")).toBe("/dashboard");
  expect(screen.getByRole("link", { name: "Deploy from GitHub" }).getAttribute("href")).toBe("/dashboard?import=github");
  expect(screen.queryByRole("link", { name: "Sign in with GitHub" })).toBeNull();
});

it("frames Rudder as an observable delivery loop with an ordered operator proof", () => {
  render(<LandingPage authenticated={false} />);

  const proof = screen.getByRole("region", { name: "The delivery loop, in plain sight." });
  expect(proof.querySelector("ol")).toBeTruthy();
  expect(screen.getByText("Repository event")).toBeTruthy();
  expect(screen.getByText("Release record")).toBeTruthy();
});

it("explains Rudder AI and the propose-only Advisor without promising automatic changes", () => {
  render(<LandingPage authenticated={false} />);

  expect(screen.getByText("Rudder AI, grounded in your workspace")).toBeTruthy();
  expect(screen.getByText("Rudder Advisor, before you deploy")).toBeTruthy();
  expect(screen.getByText(/nothing is applied automatically/i)).toBeTruthy();
});
