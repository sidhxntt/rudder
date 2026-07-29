import { afterEach, describe, expect, it, vi } from "vitest";

import { getServiceOperations, requestScale, updateServiceOperations } from "./api";

function response(body: unknown, headers: Record<string, string> = {}) {
  return {
    ok: true,
    status: 200,
    headers: new Headers(headers),
    json: async () => body,
  };
}

describe("service operations API", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("reads the envelope and preserves the ETag for a safe state update", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce(response({ desired: {}, observed: {}, version: 4, pending_reconciliation: false, updated_at: "now", history: [] }, { ETag: '"4"' }))
      .mockResolvedValueOnce(response({ desired: { replicas: 2 }, observed: {}, version: 5, pending_reconciliation: true, updated_at: "later" }, { ETag: '"5"' }));
    vi.stubGlobal("fetch", fetch);

    const envelope = await getServiceOperations("service id");
    await updateServiceOperations("service id", { replicas: 2 }, envelope.etag ?? "");

    expect(fetch.mock.calls[0][0]).toBe("/api/services/service%20id/operations?format=envelope");
    expect(fetch.mock.calls[1][1].headers["If-Match"]).toBe('"4"');
  });

  it("sends a fresh idempotency key for typed operation requests", async () => {
    const fetch = vi.fn().mockResolvedValue(response({ id: "op", service_id: "service", kind: "scale", status: "pending", requested: { replicas: 3 }, observed: {}, error_message: null, created_at: "now", completed_at: null }));
    vi.stubGlobal("fetch", fetch);

    await requestScale("service", 3);

    expect(fetch.mock.calls[0][0]).toBe("/api/services/service/operations/scale");
    expect(fetch.mock.calls[0][1].headers["Idempotency-Key"]).toEqual(expect.any(String));
    expect(fetch.mock.calls[0][1].body).toBe('{"replicas":3}');
  });
});
