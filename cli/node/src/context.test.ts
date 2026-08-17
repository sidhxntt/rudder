import { describe, expect, it } from "vitest";

import { contextFrom, mergeContext } from "./context.js";

describe("context", () => {
  it("explicit flags override selected context", () => {
    expect(mergeContext({ project: "old", environment: "prod", service: "api" }, { project: "new", environment: undefined, service: undefined }))
      .toEqual({ project: "new", environment: "prod", service: "api" });
  });

  it("parses saved context safely", () => {
    expect(contextFrom('{"project":"p","environment":"e"}')).toEqual({ project: "p", environment: "e" });
    expect(contextFrom("bad json")).toEqual({});
  });
});
