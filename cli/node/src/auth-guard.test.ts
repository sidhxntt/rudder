import { describe, expect, it } from "vitest";

import { authenticationGate } from "./auth-guard.js";

describe("authenticationGate", () => {
  it("starts GitHub login before an interactive operator command without a token", () => {
    expect(authenticationGate({ hasToken: false, noInteractive: false, isTTY: true })).toBe(
      "interactive-login",
    );
  });

  it("requires RUDDER_TOKEN rather than prompting in automation", () => {
    expect(authenticationGate({ hasToken: false, noInteractive: true, isTTY: false })).toBe(
      "noninteractive-error",
    );
  });

  it("allows an already authenticated command to proceed", () => {
    expect(authenticationGate({ hasToken: true, noInteractive: false, isTTY: true })).toBe("ready");
  });
});
