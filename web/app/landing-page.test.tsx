import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { LandingPage } from "./landing-page";

it("gives a signed-out visitor GitHub auth and local-start actions", () => {
  render(<LandingPage authenticated={false} />);

  expect(screen.getByRole("link", { name: "Sign in with GitHub" }).getAttribute("href")).toBe(
    "/api/auth/github/start",
  );
  expect(screen.getAllByRole("link", { name: "Run locally" }).every((link) => link.getAttribute("href") === "#run-locally")).toBe(true);
  expect(screen.getByText("GKE controlled beta")).toBeTruthy();
  expect(screen.getByText("In development")).toBeTruthy();
});

it("takes a signed-in visitor to the dashboard import flow", () => {
  render(<LandingPage authenticated />);

  expect(screen.getByRole("navigation", { name: "Public navigation" })).toBeTruthy();
  expect(screen.getByRole("link", { name: "Deploy from GitHub" }).getAttribute("href")).toBe(
    "/dashboard?import=github",
  );
});

it("frames Rudder as an observable delivery loop with an ordered operator proof", () => {
  render(<LandingPage authenticated={false} />);

  const proof = screen.getByRole("region", { name: "The delivery loop, in plain sight." });
  expect(proof).toBeTruthy();
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
