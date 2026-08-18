import { describe, expect, it, vi } from "vitest";

import { advisorRequest } from "./advisor.js";

describe("advisorRequest", () => {
  it("routes individual acceptance to the environment advisor endpoint", async () => {
    const request = vi.fn().mockResolvedValue({ id: "new-service" });
    await advisorRequest({ request } as never, "accept", "environment-id", { item: { kind: "addon", payload: { template: "redis" } } });
    expect(request).toHaveBeenCalledWith("POST", "/environments/environment-id/advisor/accept", { item: { kind: "addon", payload: { template: "redis" } } });
  });

  it("routes diagnosis without pretending it is deterministic", async () => {
    const request = vi.fn().mockResolvedValue({ model_generated: true, diagnosis: "Possible startup error" });
    await advisorRequest({ request } as never, "diagnose", undefined, { logs: ["boom"] });
    expect(request).toHaveBeenCalledWith("POST", "/advisor/diagnosis", { logs: ["boom"] });
  });
});
