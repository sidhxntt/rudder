import { afterEach, describe, expect, it, vi } from "vitest";

const launcher = vi.hoisted(() => ({ runLauncher: vi.fn() }));
const context = vi.hoisted(() => ({
  loadConfig: vi.fn().mockResolvedValue({ context: {}, credentials: {} }),
  mergeContext: vi.fn(() => ({})),
}));

vi.mock("./launcher.js", async importOriginal => ({ ...await importOriginal<typeof import("./launcher.js")>(), runLauncher: launcher.runLauncher }));
vi.mock("./context.js", async importOriginal => ({ ...await importOriginal<typeof import("./context.js")>(), ...context }));

import { discardSession, main } from "./index.js";
import { ApiClient } from "./client.js";

const stdinTTY = Object.getOwnPropertyDescriptor(process.stdin, "isTTY");
const stdoutTTY = Object.getOwnPropertyDescriptor(process.stdout, "isTTY");
const argv = process.argv;

afterEach(() => {
  process.argv = argv;
  if (stdinTTY) Object.defineProperty(process.stdin, "isTTY", stdinTTY); else delete (process.stdin as { isTTY?: boolean }).isTTY;
  if (stdoutTTY) Object.defineProperty(process.stdout, "isTTY", stdoutTTY); else delete (process.stdout as { isTTY?: boolean }).isTTY;
  vi.restoreAllMocks();
});

describe("main", () => {
  it("prints usage instead of launching when stdout is redirected", async () => {
    process.argv = ["node", "rudder"];
    Object.defineProperty(process.stdin, "isTTY", { configurable: true, value: true });
    Object.defineProperty(process.stdout, "isTTY", { configurable: true, value: false });
    const log = vi.spyOn(console, "log").mockImplementation(() => undefined);

    await main();

    expect(launcher.runLauncher).not.toHaveBeenCalled();
    expect(log).toHaveBeenCalledWith(expect.stringContaining("Usage: rudder"));
  });

  it("removes the old bearer token before any later protected request", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response("{}", { status: 200 }));
    vi.stubGlobal("fetch", fetcher);
    const session = { api: new ApiClient("https://cp.example", "old-token"), credentials: { token: "old-token" } };

    discardSession(session);
    await session.api.request("GET", "/protected");

    expect(session.credentials.token).toBeUndefined();
    expect(fetcher).toHaveBeenCalledWith("https://cp.example/protected", expect.objectContaining({ headers: expect.not.objectContaining({ authorization: "Bearer old-token" }) }));
  });
});
