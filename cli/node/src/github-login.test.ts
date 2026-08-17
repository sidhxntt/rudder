import { describe, expect, it, vi } from "vitest";

import { completeGitHubLogin } from "./github-login.js";

describe("completeGitHubLogin", () => {
  it("opens the server-issued browser URL and consumes the one-time token", async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ handoff_id: "opaque-handoff", authorization_url: "https://github.com/login/oauth/authorize?state=signed" })
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce({ access_token: "cli-token", expires_in: 3600 });
    const open = vi.fn();

    await expect(completeGitHubLogin({ api: { request } as never, open, wait: async () => undefined })).resolves.toMatchObject({ access_token: "cli-token" });
    expect(open).toHaveBeenCalledWith("https://github.com/login/oauth/authorize?state=signed");
    expect(request).toHaveBeenLastCalledWith("POST", "/auth/github/cli/exchange", { handoff_id: "opaque-handoff" });
  });
});
