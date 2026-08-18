import type { ApiClient } from "./client.js";

export async function advisorRequest(
  api: Pick<ApiClient, "request">,
  action: "scan" | "accept" | "diagnose",
  environmentId: string | undefined,
  body: unknown,
): Promise<unknown> {
  if (action === "diagnose") return api.request("POST", "/advisor/diagnosis", body);
  if (!environmentId) throw new Error(`advisor ${action} requires a selected environment.`);
  return api.request("POST", `/environments/${environmentId}/advisor/${action}`, body);
}
