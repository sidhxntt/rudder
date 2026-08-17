import { expect, it } from "vitest";

import { canvasOperatorContext, workspaceDashboardHref } from "./canvas";

it("returns canvas operators to the signed-in workspace dashboard", () => {
  expect(workspaceDashboardHref()).toBe("/dashboard");
});

it("gives a first deployment a clear topology starting point", () => {
  expect(canvasOperatorContext({ serviceCount: 0, selectedServiceName: null })).toEqual({
    eyebrow: "Deployment topology",
    title: "No service topology yet",
    description: "Create a service to map its release and private dependencies here.",
    command: "rudder service create",
  });
});

it("keeps the selected service in the canvas context", () => {
  expect(canvasOperatorContext({ serviceCount: 3, selectedServiceName: "api" })).toEqual({
    eyebrow: "Deployment topology",
    title: "api selected",
    description: "Inspect its release, runtime, and private connections in the panel.",
    command: null,
  });
});
