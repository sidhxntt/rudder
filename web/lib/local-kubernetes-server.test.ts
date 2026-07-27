// @vitest-environment node

import { describe, expect, it, vi } from "vitest";

import {
  bootstrapLocalKubernetesRuntime,
  isLocalKubernetesAutoBootstrapEnabled,
  waitForKubernetesControlPlane,
} from "./local-kubernetes-server";

describe("local Kubernetes bootstrap", () => {
  it("creates Kind and restarts the control plane before a local release", async () => {
    const runMake = vi.fn().mockResolvedValue(undefined);
    const waitForHealth = vi.fn().mockResolvedValue(undefined);
    const isReady = vi.fn().mockResolvedValue(false);

    await bootstrapLocalKubernetesRuntime({
      rootDir: "/workspace/rudder",
      runMake,
      waitForHealth,
      isReady,
    });

    expect(runMake).toHaveBeenNthCalledWith(1, "kind-up", "/workspace/rudder");
    expect(runMake).toHaveBeenNthCalledWith(2, "kind-control-plane", "/workspace/rudder");
    expect(waitForHealth).toHaveBeenCalledOnce();
  });

  it("reuses an already-ready Kind runtime without restarting the control plane", async () => {
    const runMake = vi.fn().mockResolvedValue(undefined);
    const waitForHealth = vi.fn().mockResolvedValue(undefined);

    await bootstrapLocalKubernetesRuntime({
      isReady: vi.fn().mockResolvedValue(true),
      runMake,
      waitForHealth,
    });

    expect(runMake).not.toHaveBeenCalled();
    expect(waitForHealth).not.toHaveBeenCalled();
  });

  it("waits for the Kubernetes control plane rather than any healthy control plane", async () => {
    const request = vi
      .fn()
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ runtime: "docker" }),
      })
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        json: async () => ({ runtime: "kubernetes" }),
      });

    await waitForKubernetesControlPlane({ request, pollMs: 0 });

    expect(request).toHaveBeenCalledTimes(2);
  });

  it("does not enable host tooling outside the local development mode", () => {
    expect(isLocalKubernetesAutoBootstrapEnabled({ NODE_ENV: "production" })).toBe(false);
    expect(
      isLocalKubernetesAutoBootstrapEnabled({
        NODE_ENV: "development",
        RUDDER_LOCAL_KUBERNETES_AUTO_BOOTSTRAP: "false",
      }),
    ).toBe(false);
    expect(isLocalKubernetesAutoBootstrapEnabled({ NODE_ENV: "development" })).toBe(true);
  });
});
