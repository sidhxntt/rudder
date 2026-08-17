import { EventEmitter } from "node:events";
import { describe, expect, it, vi } from "vitest";

const { spawn } = vi.hoisted(() => ({ spawn: vi.fn() }));

vi.mock("node:child_process", () => ({ spawn }));
vi.mock("node:os", () => ({ platform: () => "linux" }));

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

  it("prints a copyable URL when the browser process exits unsuccessfully", async () => {
    const child = Object.assign(new EventEmitter(), { unref: vi.fn() });
    spawn.mockImplementationOnce(() => {
      queueMicrotask(() => child.emit("exit", 1));
      return child;
    });
    const request = vi.fn()
      .mockResolvedValueOnce({ id: "opaque", authorization_url: "https://github.com/login/oauth/authorize?state=signed" })
      .mockResolvedValueOnce({ access_token: "cli-token" });
    const writeError = vi.fn();

    await completeGitHubLogin({ api: { request } as never, writeError });

    expect(writeError).toHaveBeenCalledWith(expect.stringContaining("https://github.com/login/oauth/authorize?state=signed"));
  });
});
