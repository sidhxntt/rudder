/** Prepare the local Kind runtime before a development import is submitted. */
export async function ensureLocalKubernetesRuntime(): Promise<void> {
  const response = await fetch("/api/local-kubernetes/bootstrap", { method: "POST" });
  if (response.ok) return;

  const body = await response.json().catch(() => null) as { detail?: string } | null;
  throw new Error(body?.detail ?? "Could not prepare the local Kubernetes runtime.");
}
