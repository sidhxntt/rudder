import { describe, expect, it } from "vitest";

import { composeAdvisorGraph, resolveAdvisorVariableTarget } from "./canvas";

describe("composeAdvisorGraph", () => {
  it("renders proposed services and add-ons as ghost canvas nodes with dependency edges", () => {
    const graph = composeAdvisorGraph([
      { id: "service:app", kind: "service", status: "proposed", payload: { name: "app" } },
      { id: "addon:postgres", kind: "addon", status: "proposed", payload: { template: "postgres" } },
      { id: "variable:database-url", kind: "variable", status: "proposed", payload: { service: "app", key: "DATABASE_URL" } },
    ]);
    expect(graph.nodes.map((node) => node.id)).toEqual(["advisor:service:app", "advisor:addon:postgres"]);
    expect(graph.nodes.every((node) => node.type === "advisor")).toBe(true);
    expect(graph.edges).toHaveLength(1);
  });
});

it("uses the explicitly selected service for a variable proposal", () => {
  expect(resolveAdvisorVariableTarget("selected-id", "app", [{ id: "app-id", name: "app" }] as never)).toBe("selected-id");
  expect(resolveAdvisorVariableTarget("", "app", [{ id: "app-id", name: "app" }] as never)).toBe("app-id");
});
