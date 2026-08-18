import { describe, expect, it, vi } from "vitest";

import { ApiClient, ApiError } from "./client.js";

describe("ApiClient", () => {
  it("adds the token and returns JSON", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response(JSON.stringify({ id: "p1" }), { status: 201 }));
    const client = new ApiClient("https://cp.example/", "token", fetcher);

    await expect(client.request("POST", "/projects", { name: "demo" })).resolves.toEqual({ id: "p1" });
    expect(fetcher).toHaveBeenCalledWith("https://cp.example/projects", expect.objectContaining({
      method: "POST", headers: expect.objectContaining({ authorization: "Bearer token" }),
      body: JSON.stringify({ name: "demo" }),
    }));
  });

  it("turns API failures into an actionable error", async () => {
    const client = new ApiClient("https://cp.example", undefined, vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: { message: "No such service" } }), { status: 404 }),
    ));
    await expect(client.request("GET", "/services/missing")).rejects.toMatchObject({ status: 404, message: "No such service" } satisfies Partial<ApiError>);
  });
});
