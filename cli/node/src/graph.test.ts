import { describe, expect, it } from "vitest";

import { serviceGraph } from "./graph.js";

describe("serviceGraph", () => {
  it("reports only persisted Compose release ownership", () => {
    expect(serviceGraph([
      { id: "app", name: "api", source_repo: "acme/api", build_config: { compose_service: "app", compose_role: "app" } },
      { id: "db", name: "postgres", source_repo: null, build_config: { compose_service: "postgres", compose_role: "database", managed_by_service_id: "app" } },
    ])).toEqual({
      services: expect.any(Array),
      relationships: [{ owner_id: "app", service_id: "db", relationship: "included in release" }],
    });
  });
});
