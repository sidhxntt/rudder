import { describe, expect, it } from "vitest";

import { composeReleaseOwnerId } from "./compose-lifecycle";

describe("composeReleaseOwnerId", () => {
  it("uses the source-backed application instead of the first managed add-on", () => {
    const services = [
      { id: "postgres", source_repo: null, build_config: { managed_image: "postgres:16", compose_service: "postgres" } },
      { id: "redis", source_repo: null, build_config: { managed_image: "redis:7", compose_service: "redis" } },
      { id: "api", source_repo: "acme/api", build_config: { compose_service: "app" } },
    ];

    expect(composeReleaseOwnerId(services)).toBe("api");
  });
});
