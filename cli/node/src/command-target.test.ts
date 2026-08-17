import { describe, expect, it } from "vitest";

import { commandTarget } from "./command-target.js";

describe("commandTarget", () => {
  it("uses the first positional argument for commands without an action", () => {
    expect(commandTarget("bea76dee-cad9-41d7-81ab-f252040f4f38", [])).toBe("bea76dee-cad9-41d7-81ab-f252040f4f38");
  });

  it("uses the remaining argument for action-based commands", () => {
    expect(commandTarget("list", ["bea76dee-cad9-41d7-81ab-f252040f4f38"])).toBe("bea76dee-cad9-41d7-81ab-f252040f4f38");
  });
});
