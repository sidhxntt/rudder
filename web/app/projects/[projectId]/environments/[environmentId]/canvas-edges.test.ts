import { expect, it } from "vitest";

import { composeEdges } from "./canvas";

it("labels compose lifecycle edges without claiming an unproven dependency", () => {
  const edges = composeEdges([
    {
      id: "api",
      name: "api",
      source_repo: "acme/api",
      build_config: { compose_service: "app", compose_role: "app" },
    },
    {
      id: "postgres",
      name: "postgres",
      source_repo: null,
      build_config: { compose_service: "postgres", compose_role: "database" },
    },
  ] as never, "api");

  expect(edges).toHaveLength(1);
  expect(edges[0]?.label).toBe("included in release");
  expect(edges[0]?.ariaLabel).toBe("api includes postgres in its release");
});
