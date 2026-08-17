import { describe, expect, it, vi } from "vitest";

import { completeGitHubLogin } from "./github-login.js";

describe("completeGitHubLogin", () => {
  it("opens the server URL and consumes its token", async () => {
    const request = vi.fn()
      .mockResolvedValueOnce({ id: "opaque", authorization_url: "https://github.com/login/oauth/authorize?state=signed" })
      .mockResolvedValueOnce(null)
      .mockResolvedValueOnce({ access_token: "cli-token", expires_in: 3600 });
    const open = vi.fn().mockResolvedValue(undefined);
    const wait = vi.fn().mockResolvedValue(undefined);

    await expect(completeGitHubLogin({ api: { request } as never, open, wait }))
      .resolves.toMatchObject({ access_token: "cli-token" });

    expect(open).toHaveBeenCalledWith("https://github.com/login/oauth/authorize?state=signed");
    expect(wait).toHaveBeenCalledTimes(1);
    expect(request).toHaveBeenNthCalledWith(1, "POST", "/auth/authorizations");
    expect(request).toHaveBeenNthCalledWith(2, "POST", "/auth/authorizations/opaque/consume");
    expect(request).toHaveBeenNthCalledWith(3, "POST", "/auth/authorizations/opaque/consume");
  });
});
